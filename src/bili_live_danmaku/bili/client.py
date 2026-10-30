from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from ..models import ChatMessage, ConnectionStatus
from .events import EventProcessor
from .packets import auth_packet, heartbeat_packet, iter_documents
from .wbi import key_from_url, make_query, mixin_key

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
    "Gecko/20100101 Firefox/133.0"
)
LIVE_API = "https://api.live.bilibili.com"
MAIN_API = "https://api.bilibili.com"


@dataclass(frozen=True, slots=True)
class DanmuEndpoint:
    host: str
    port: int
    token: str


def account_mid(cookie: str) -> int:
    match = re.search(r"(?:^|;\s*)DedeUserID=(\d+)", cookie)
    return int(match.group(1)) if match else 0


def has_login_cookie(cookie: str) -> bool:
    return bool(re.search(r"(?:^|;\s*)SESSDATA=[^;]+", cookie))


def _room_number(text: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{1,12})(?!\d)", text)
    return int(match.group(1)) if match else None


class BiliApi:
    def __init__(self, cookie: str) -> None:
        self.cookie = cookie.strip()
        self._buvid3 = self._cookie_value("buvid3")
        self._mixin: str | None = None
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    async def close(self) -> None:
        await self._client.aclose()

    def _cookie_value(self, name: str) -> str:
        match = re.search(rf"(?:^|;\s*){re.escape(name)}=([^;]+)", self.cookie)
        return match.group(1) if match else ""

    async def _ensure_buvid(self) -> None:
        if self._buvid3:
            return
        response = await self._client.get(
            f"{MAIN_API}/x/frontend/finger/spi", headers=self._headers()
        )
        data = self._json(response)
        value = data.get("data")
        if isinstance(value, dict) and isinstance(value.get("b_3"), str):
            self._buvid3 = value["b_3"]
        if not self._buvid3:
            raise RuntimeError("B站设备 ID 获取失败")

    def _headers(self) -> dict[str, str]:
        cookie = self.cookie
        if self._buvid3 and "buvid3=" not in cookie:
            prefix = f"buvid3={self._buvid3}; b_nut={int(time.time())}"
            cookie = f"{prefix}; {cookie}" if cookie else prefix
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://live.bilibili.com/",
            "Origin": "https://live.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if cookie:
            headers["Cookie"] = cookie
        return headers

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise RuntimeError(f"B站返回了非 JSON 响应（HTTP {response.status_code}）") from exc
        if not isinstance(value, dict):
            raise RuntimeError("B站返回了意外的 JSON 结构")
        return value

    async def _get_json(self, url: str) -> dict[str, Any]:
        response = await self._client.get(url, headers=self._headers())
        response.raise_for_status()
        return self._json(response)

    async def mixin(self) -> str:
        if self._mixin:
            return self._mixin
        data = await self._get_json(f"{MAIN_API}/x/web-interface/nav")
        wbi = data.get("data")
        wbi_img = wbi.get("wbi_img") if isinstance(wbi, dict) else None
        if not isinstance(wbi_img, dict):
            raise RuntimeError("B站 WBI 密钥响应缺少 wbi_img")
        img = key_from_url(str(wbi_img.get("img_url", "")))
        sub = key_from_url(str(wbi_img.get("sub_url", "")))
        self._mixin = mixin_key(img, sub)
        return self._mixin

    async def resolve_room(self, room: str) -> int:
        candidate = _room_number(room)
        if candidate is None:
            response = await self._client.get(room, headers=self._headers())
            response.raise_for_status()
            patterns = (
                r"live\.bilibili\.com/(\d+)",
                r'"roomid"\s*:\s*(\d+)',
                r'"room_id"\s*:\s*(\d+)',
            )
            for pattern in patterns:
                match = re.search(pattern, response.text)
                if match:
                    candidate = int(match.group(1))
                    break
        if candidate is None or candidate <= 0:
            raise RuntimeError("没有从直播地址中找到房间号")
        data = await self._get_json(f"{LIVE_API}/room/v1/Room/room_init?id={candidate}")
        if data.get("code") != 0:
            raise RuntimeError(f"room_init 失败：{data.get('message') or data.get('code')}")
        room_data = data.get("data")
        real_id = room_data.get("room_id") if isinstance(room_data, dict) else None
        if not isinstance(real_id, int) or real_id <= 0:
            raise RuntimeError("room_init 没有返回真实房间号")
        return real_id

    async def danmu_endpoint(self, room_id: int) -> DanmuEndpoint:
        params = {
            "id": str(room_id),
            "type": "0",
            "context_type": "0",
            "wts": str(int(time.time())),
        }
        query = make_query(params, await self.mixin())
        data = await self._get_json(
            f"{LIVE_API}/xlive/web-room/v1/index/getDanmuInfo?{query}"
        )
        if data.get("code") != 0:
            raise RuntimeError(
                f"getDanmuInfo 失败（{data.get('code')}）：{data.get('message')}"
            )
        payload = data.get("data")
        hosts = payload.get("host_list") if isinstance(payload, dict) else None
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(hosts, list) or not hosts or not isinstance(token, str):
            raise RuntimeError("getDanmuInfo 没有返回可用节点")
        first = hosts[0]
        if not isinstance(first, dict):
            raise RuntimeError("getDanmuInfo 节点格式异常")
        host = first.get("host")
        port = first.get("wss_port")
        if not isinstance(host, str) or not host or not isinstance(port, int):
            raise RuntimeError("getDanmuInfo 节点缺少 host 或 wss_port")
        return DanmuEndpoint(host, port, token)


StatusCallback = Callable[[ConnectionStatus], Awaitable[None]]
MessageCallback = Callable[[ChatMessage], Awaitable[None]]


class BiliClient:
    def __init__(
        self,
        room: str,
        cookie: str,
        on_status: StatusCallback,
        on_message: MessageCallback,
        entry_merge_seconds: float,
        gift_merge_seconds: float,
    ) -> None:
        self.room = room
        self.cookie = cookie
        self.on_status = on_status
        self.on_message = on_message
        self.entry_merge_seconds = entry_merge_seconds
        self.gift_merge_seconds = gift_merge_seconds
        self._stopped = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="bili-client")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _status(self, status: ConnectionStatus) -> None:
        await self.on_status(status)

    async def run(self) -> None:
        backoff = 1.0
        while not self._stopped.is_set():
            try:
                await self._connect_once()
                if self._stopped.is_set():
                    return
                raise RuntimeError("B站弹幕连接已关闭")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stopped.is_set():
                    return
                message = str(exc) or exc.__class__.__name__
                await self._status(
                    ConnectionStatus(
                        state="reconnecting",
                        message=f"连接中断，{backoff:.0f} 秒后重试",
                        room_id=_room_number(self.room),
                        cookie_present=has_login_cookie(self.cookie),
                        last_error=message,
                    )
                )
                await asyncio.sleep(backoff + random.uniform(0, 0.4))
                backoff = min(30.0, backoff * 2)

    async def _connect_once(self) -> None:
        await self._status(
            ConnectionStatus(
                state="connecting",
                message="正在解析直播间",
                room_id=_room_number(self.room),
                cookie_present=has_login_cookie(self.cookie),
            )
        )
        api = BiliApi(self.cookie)
        processor = EventProcessor(
            self.on_message, self.entry_merge_seconds, self.gift_merge_seconds
        )
        try:
            await api._ensure_buvid()
            real_room = await api.resolve_room(self.room)
            endpoint = await api.danmu_endpoint(real_room)
            await self._status(
                ConnectionStatus(
                    state="connecting",
                    message="正在连接弹幕服务器",
                    room_id=_room_number(self.room),
                    real_room_id=real_room,
                    cookie_present=has_login_cookie(self.cookie),
                )
            )
            url = f"wss://{endpoint.host}:{endpoint.port}/sub"
            headers = {
                "User-Agent": USER_AGENT,
                "Origin": "https://live.bilibili.com",
                "Referer": "https://live.bilibili.com/",
                "Cookie": api._headers().get("Cookie", ""),
            }
            async with websockets.connect(
                url,
                additional_headers=headers,
                open_timeout=15,
                close_timeout=5,
                ping_interval=None,
                max_size=8 * 1024 * 1024,
            ) as websocket:
                await websocket.send(
                    auth_packet(real_room, endpoint.token, account_mid(self.cookie))
                )
                authenticated = False
                next_heartbeat = time.monotonic() + 30
                while not self._stopped.is_set():
                    timeout = max(0.1, next_heartbeat - time.monotonic())
                    try:
                        frame = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                    except TimeoutError:
                        await websocket.send(heartbeat_packet())
                        next_heartbeat = time.monotonic() + 30
                        continue
                    if time.monotonic() >= next_heartbeat:
                        await websocket.send(heartbeat_packet())
                        next_heartbeat = time.monotonic() + 30
                    if isinstance(frame, str):
                        try:
                            document = json.loads(frame)
                        except ValueError:
                            continue
                        documents = [document] if isinstance(document, dict) else []
                    else:
                        documents = list(iter_documents(frame))
                    for document in documents:
                        if document.get("code") == 0 and not authenticated:
                            authenticated = True
                            await self._status(
                                ConnectionStatus(
                                    state="connected",
                                    message="弹幕已连接",
                                    room_id=_room_number(self.room),
                                    real_room_id=real_room,
                                    cookie_present=has_login_cookie(self.cookie),
                                )
                            )
                            continue
                        await processor.handle(document)
        except (ConnectionClosed, OSError) as exc:
            raise RuntimeError(f"弹幕连接关闭：{exc}") from exc
        finally:
            await processor.shutdown()
            await api.close()
