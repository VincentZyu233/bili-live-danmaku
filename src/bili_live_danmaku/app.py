from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from .bili.client import BiliClient, has_login_cookie
from .config import ConfigStore, atomic_write_text, default_cookie_file
from .history import HistoryStore
from .media import MAX_FONT_BYTES, FontLibrary, ImageProxy
from .models import (
    AppConfig,
    ChatMessage,
    ConnectionStatus,
    EventEnvelope,
    Fragment,
    MessageKind,
    UserType,
)

STATIC_DIR = Path(__file__).parent / "static"


class CookiePayload(BaseModel):
    cookie: str = Field(min_length=1, max_length=16_384)


class BroadcastHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.sequence = 0

    def envelope(self, event_type: str, payload: object) -> dict[str, Any]:
        self.sequence += 1
        envelope = EventEnvelope(
            type=event_type,  # type: ignore[arg-type]
            sequence=self.sequence,
            server_time_ms=int(time.time() * 1000),
            payload=payload,
        )
        return envelope.model_dump(mode="json")

    async def add(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)

    def remove(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)

    async def send(self, websocket: WebSocket, event_type: str, payload: object) -> None:
        await websocket.send_json(self.envelope(event_type, payload))

    async def broadcast(self, event_type: str, payload: object) -> None:
        if not self.clients:
            return
        document = self.envelope(event_type, payload)
        dead: list[WebSocket] = []
        for client in tuple(self.clients):
            try:
                await asyncio.wait_for(client.send_json(document), timeout=1.0)
            except Exception:
                dead.append(client)
        for client in dead:
            self.clients.discard(client)


class Runtime:
    def __init__(
        self,
        config_store: ConfigStore,
        cookie_override: str | None = None,
        cookie_file_override: str | None = None,
        demo: bool = False,
    ) -> None:
        self.config_store = config_store
        self.config = config_store.load()
        self.cookie_override = cookie_override
        self.cookie_file_override = cookie_file_override
        self.demo = demo
        self.hub = BroadcastHub()
        self.history = HistoryStore(config_store.data_dir)
        self.images = ImageProxy(config_store.data_dir / "cache" / "images")
        self.fonts = FontLibrary(config_store.data_dir / "fonts")
        self.status = ConnectionStatus()
        self.client: BiliClient | None = None
        self._client_lock = asyncio.Lock()
        self._demo_task: asyncio.Task[None] | None = None
        self._status_task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._recent_messages: deque[float] = deque()

    async def start(self) -> None:
        self._stopped.clear()
        self._status_task = asyncio.create_task(self._status_loop(), name="status-loop")
        if self.demo:
            self.status = ConnectionStatus(state="connected", message="演示模式")
            self._demo_task = asyncio.create_task(self._run_demo(), name="demo-source")
        elif self.config.auto_connect and self.config.room.strip():
            await self.restart_client()
        else:
            self.status = ConnectionStatus(
                message="等待配置直播间", cookie_present=self.cookie_present()
            )

    async def stop(self) -> None:
        self._stopped.set()
        if self._demo_task is not None:
            self._demo_task.cancel()
            await asyncio.gather(self._demo_task, return_exceptions=True)
            self._demo_task = None
        if self._status_task is not None:
            self._status_task.cancel()
            await asyncio.gather(self._status_task, return_exceptions=True)
            self._status_task = None
        await self._stop_client()
        await self.history.flush()
        await self.images.close()

    async def _stop_client(self) -> None:
        if self.client is not None:
            await self.client.stop()
            self.client = None

    def cookie_path(self) -> Path:
        selected = self.cookie_file_override or self.config.cookie_file
        fallback = default_cookie_file(self.config_store.data_dir)
        return Path(selected or fallback).expanduser().resolve()

    def read_cookie(self) -> str:
        if self.cookie_override is not None:
            return self.cookie_override.strip()
        try:
            return self.cookie_path().read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def cookie_present(self) -> bool:
        return has_login_cookie(self.read_cookie())

    async def restart_client(self) -> None:
        async with self._client_lock:
            await self._stop_client()
            if not self.config.room.strip():
                self.status = ConnectionStatus(
                    message="等待配置直播间", cookie_present=self.cookie_present()
                )
                await self.hub.broadcast("status", self.status.model_dump(mode="json"))
                return
            self.client = BiliClient(
                room=self.config.room,
                cookie=self.read_cookie(),
                on_status=self._on_status,
                on_message=self._on_message,
                entry_merge_seconds=self.config.entry_merge_seconds,
                gift_merge_seconds=self.config.gift_merge_seconds,
            )
            self.client.start()

    async def _on_status(self, status: ConnectionStatus) -> None:
        previous_room = self.status.real_room_id
        self.status = status
        if status.real_room_id and status.real_room_id != previous_room:
            self.history.select_room(status.real_room_id, self.config.history_lines)
            messages = await self.history.load(status.real_room_id, self.config.history_lines)
            await self.hub.broadcast(
                "history", [message.model_dump(mode="json") for message in messages]
            )
        await self.hub.broadcast("status", status.model_dump(mode="json"))

    async def _on_message(self, message: ChatMessage) -> None:
        self.history.append_current(message)
        await self.hub.broadcast("event", message.model_dump(mode="json"))
        now = time.monotonic()
        self._recent_messages.append(now)
        while self._recent_messages and now - self._recent_messages[0] > 10:
            self._recent_messages.popleft()

    async def _status_loop(self) -> None:
        while not self._stopped.is_set():
            await asyncio.sleep(2)
            now = time.monotonic()
            while self._recent_messages and now - self._recent_messages[0] > 10:
                self._recent_messages.popleft()
            rate = round(len(self._recent_messages) / 10, 2)
            if rate != self.status.message_rate:
                self.status.message_rate = rate
                await self.hub.broadcast("status", self.status.model_dump(mode="json"))

    async def save_config(self, config: AppConfig) -> None:
        previous = self.config
        if not config.cookie_file:
            config.cookie_file = str(default_cookie_file(self.config_store.data_dir))
        self.config_store.save(config)
        self.config = config
        await self.hub.broadcast("config", config.model_dump(mode="json"))
        connection_changed = any(
            (
                previous.room != config.room,
                previous.cookie_file != config.cookie_file,
                previous.entry_merge_seconds != config.entry_merge_seconds,
                previous.gift_merge_seconds != config.gift_merge_seconds,
                previous.auto_connect != config.auto_connect,
            )
        )
        if connection_changed and not self.demo:
            await self.restart_client()

    async def import_cookie(self, cookie: str) -> None:
        cleaned = cookie.strip()
        if not cleaned:
            raise ValueError("Cookie 不能为空")
        path = self.cookie_path()
        await asyncio.to_thread(atomic_write_text, path, cleaned)
        self.status.cookie_present = self.cookie_present()
        await self.hub.broadcast("status", self.status.model_dump(mode="json"))
        if not self.demo:
            await self.restart_client()

    async def delete_cookie(self) -> None:
        path = self.cookie_path()
        try:
            path.relative_to(self.config_store.data_dir)
        except ValueError as exc:
            raise ValueError("只能从应用数据目录中删除 Cookie") from exc
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            pass
        self.status.cookie_present = False
        await self.hub.broadcast("status", self.status.model_dump(mode="json"))
        if not self.demo:
            await self.restart_client()

    def room_for_history(self) -> int | None:
        if self.status.real_room_id:
            return self.status.real_room_id
        match = re.search(r"(?<!\d)(\d{1,12})(?!\d)", self.config.room)
        return int(match.group(1)) if match else None

    async def snapshot(self) -> dict[str, Any]:
        room_id = self.room_for_history()
        history = (
            await self.history.load(room_id, self.config.history_lines) if room_id else []
        )
        return {
            "config": self.config.model_dump(mode="json"),
            "status": self.status.model_dump(mode="json"),
            "history": [message.model_dump(mode="json") for message in history],
            "cookie_present": self.cookie_present(),
            "cookie_file": str(self.cookie_path()),
        }

    async def emit_demo(self, count: int = 10) -> None:
        for message in demo_messages()[: max(1, min(count, 30))]:
            await self.hub.broadcast("event", message.model_dump(mode="json"))
            now = time.monotonic()
            self._recent_messages.append(now)
            while self._recent_messages and now - self._recent_messages[0] > 10:
                self._recent_messages.popleft()

    async def _run_demo(self) -> None:
        messages = demo_messages()
        index = 0
        showed_paid = False
        while not self._stopped.is_set():
            message = messages[index % len(messages)].model_copy(deep=True)
            index += 1
            if message.kind == MessageKind.PAID and showed_paid:
                await asyncio.sleep(1.1)
                continue
            if message.kind == MessageKind.PAID:
                showed_paid = True
            await self._on_message(message)
            await asyncio.sleep(1.1)


def _demo_message(kind: MessageKind, user: str, text: str, **kwargs: Any) -> ChatMessage:
    return ChatMessage(
        id=uuid.uuid4().hex,
        kind=kind,
        user=user,
        parts=[Fragment(type="text", text=text)],
        timestamp_ms=int(time.time() * 1000),
        **kwargs,
    )


def demo_messages() -> list[ChatMessage]:
    return [
        _demo_message(MessageKind.TEXT, "Loyers", "这个圆角面板看起来不错", user_color="#79d7ff"),
        _demo_message(MessageKind.GIFT, "红桃老K_-", "投喂 小心心", count=10, user_color="#ff91c8"),
        _demo_message(MessageKind.ENTRY, "新观众", "进入了直播间"),
        _demo_message(MessageKind.LIKE, "点赞的人", "为主播点赞了", avatar_url=None),
        _demo_message(
            MessageKind.PAID,
            "醒目留言用户",
            "今晚的直播效果很清楚，圆角底板也很舒服！",
            amount="CN¥30",
            amount_value=30,
            dwell_ms=60_000,
            user_type=UserType.MEMBER,
        ),
        _demo_message(
            MessageKind.MEMBERSHIP,
            "舰长用户",
            "开通了舰长",
            amount="舰长 · CN¥138",
            user_type=UserType.MEMBER,
        ),
        _demo_message(MessageKind.TEXT, "表情测试", "[汤圆] 自定义字体与表情 token 测试"),
        _demo_message(
            MessageKind.TEXT,
            "长消息测试",
            "这是一条较长的弹幕，用来检查中文换行、圆角底板内边距以及底部对齐是否正常。",
        ),
    ]


def create_app(runtime: Runtime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="Bili Live Danmaku", lifespan=lifespan)
    app.state.runtime = runtime

    @app.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:
        return RedirectResponse("/admin")

    @app.get("/admin", include_in_schema=False)
    async def admin_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "admin.html", headers={"Cache-Control": "no-store"})

    @app.get("/overlay", include_in_schema=False)
    async def overlay_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "overlay.html", headers={"Cache-Control": "no-store"})

    @app.get("/static/{path:path}", include_in_schema=False)
    async def static_file(path: str) -> FileResponse:
        target = (STATIC_DIR / path).resolve()
        if not target.is_relative_to(STATIC_DIR.resolve()) or not target.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(target)

    @app.get("/api/status")
    async def api_status() -> dict[str, Any]:
        return {
            "status": runtime.status.model_dump(mode="json"),
            "cookie_present": runtime.cookie_present(),
            "cookie_file": str(runtime.cookie_path()),
            "demo": runtime.demo,
        }

    @app.get("/api/config")
    async def get_config() -> AppConfig:
        return runtime.config

    @app.put("/api/config")
    async def put_config(config: AppConfig) -> AppConfig:
        await runtime.save_config(config)
        return runtime.config

    @app.post("/api/cookie")
    async def import_cookie(payload: CookiePayload) -> dict[str, bool]:
        try:
            await runtime.import_cookie(payload.cookie)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.delete("/api/cookie")
    async def delete_cookie() -> dict[str, bool]:
        try:
            await runtime.delete_cookie()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/restart")
    async def restart() -> dict[str, bool]:
        await runtime.restart_client()
        return {"ok": True}

    @app.post("/api/demo")
    async def send_demo(count: int = 8) -> dict[str, bool]:
        await runtime.emit_demo(count)
        return {"ok": True}

    @app.get("/api/fonts")
    async def list_fonts() -> dict[str, object]:
        return {
            "system": runtime.fonts.system_fonts(),
            "uploaded": runtime.fonts.uploaded(),
        }

    @app.post("/api/fonts")
    async def upload_font(file: Annotated[UploadFile, File()]) -> dict[str, str]:
        data = await file.read(MAX_FONT_BYTES + 1)
        try:
            saved = runtime.fonts.save(file.filename or "font.ttf", data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return saved

    @app.get("/fonts/{name}", include_in_schema=False)
    async def font_file(name: str) -> FileResponse:
        path = runtime.fonts.resolve(name)
        if path is None:
            raise HTTPException(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/media", include_in_schema=False)
    async def media(url: str) -> FileResponse:
        try:
            path, content_type = await runtime.images.get(url)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="图片获取失败") from exc
        return FileResponse(
            path,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        host = websocket.headers.get("host")
        if origin and host and urlparse(origin).netloc != host:
            await websocket.close(code=1008)
            return
        await runtime.hub.add(websocket)
        try:
            await runtime.hub.send(websocket, "snapshot", await runtime.snapshot())
            while True:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_json(
                        {"type": "pong", "server_time_ms": int(time.time() * 1000)}
                    )
        except WebSocketDisconnect:
            pass
        finally:
            runtime.hub.remove(websocket)

    return app
