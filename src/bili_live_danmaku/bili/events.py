from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from ..models import ChatMessage, Fragment, MessageKind, UserType
from .protobuf import decode_pb_base64


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _clean(text: object) -> str:
    if not isinstance(text, str):
        return ""
    return text.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()


def https_url(value: object) -> str | None:
    url = _clean(value)
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[7:]
    return url


def _color(value: object) -> str | None:
    number = _as_int(value)
    return f"#{number & 0xFFFFFF:06x}" if number > 0 else None


def _guard_level(*values: object) -> int:
    return max((_as_int(value) for value in values), default=0)


def _split_fragments(text: str, emotes: dict[str, Fragment]) -> list[Fragment]:
    if not text:
        return []
    if not emotes:
        return [Fragment(type="text", text=text)]
    tokens = sorted(emotes, key=len, reverse=True)
    parts: list[Fragment] = []
    run: list[str] = []
    index = 0
    while index < len(text):
        token = next((candidate for candidate in tokens if text.startswith(candidate, index)), None)
        if token is None:
            run.append(text[index])
            index += 1
            continue
        if run:
            parts.append(Fragment(type="text", text="".join(run)))
            run.clear()
        parts.append(emotes[token].model_copy(deep=True))
        index += len(token)
    if run:
        parts.append(Fragment(type="text", text="".join(run)))
    return parts


def _emote_options(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), {})
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _message(kind: MessageKind, user: str) -> ChatMessage:
    return ChatMessage(id=uuid.uuid4().hex, kind=kind, user=_clean(user))


def dwell_for(amount: int) -> int:
    if amount >= 2000:
        return 2 * 60 * 60 * 1000
    if amount >= 1000:
        return 60 * 60 * 1000
    if amount >= 500:
        return 30 * 60 * 1000
    if amount >= 100:
        return 5 * 60 * 1000
    if amount >= 50:
        return 2 * 60 * 1000
    return 60 * 1000


def _danmu(document: dict[str, Any]) -> ChatMessage | None:
    info = _as_list(document.get("info"))
    if len(info) < 3:
        return None
    head = _as_list(info[0])
    text = _clean(info[1])
    user_info = _as_list(info[2])
    fallback_user = _clean(user_info[1]) if len(user_info) > 1 else ""
    tail = _as_dict(head[15]) if len(head) > 15 else {}
    user = _as_dict(tail.get("user"))
    base = _as_dict(user.get("base"))

    message = _message(MessageKind.TEXT, _clean(base.get("name")) or fallback_user)
    message.timestamp_ms = _as_int(head[4]) if len(head) > 4 else 0
    message.avatar_url = https_url(base.get("face"))
    message.user_color = _color(base.get("name_color"))

    guard = _guard_level(
        _as_dict(user.get("guard")).get("guard_level"),
        _as_dict(user.get("medal")).get("guard_level"),
    )
    if guard >= 3:
        message.user_type = UserType.MEMBER

    dm_type = _as_int(head[12]) if len(head) > 12 else 0
    if dm_type == 1:
        options = _emote_options(head[13] if len(head) > 13 else None)
        message.parts = [
            Fragment(
                type="emote",
                text=text,
                url=https_url(options.get("url")),
                px=_as_int(options.get("height")),
            )
        ]
        return message

    emote_map: dict[str, Fragment] = {}
    extra = tail.get("extra")
    if isinstance(extra, str) and extra:
        try:
            parsed = json.loads(extra)
        except ValueError:
            parsed = {}
        for token, item in _as_dict(_as_dict(parsed).get("emots")).items():
            emote = _as_dict(item)
            emote_map[token] = Fragment(
                type="emote",
                text=token,
                url=https_url(emote.get("url")),
                px=_as_int(emote.get("height")),
            )
    message.parts = _split_fragments(text, emote_map)
    return message


def _entry(document: dict[str, Any]) -> ChatMessage | None:
    pb = decode_pb_base64(_as_dict(document.get("data")).get("pb"))
    if pb is None:
        return None
    user = _clean(pb.get_str(2))
    if not user:
        return None
    message = _message(MessageKind.ENTRY, user)
    message.timestamp_ms = pb.get_num(8)
    message.parts = [Fragment(type="text", text="进入了直播间")]
    return message


def _gift(document: dict[str, Any]) -> ChatMessage | None:
    root = decode_pb_base64(_as_dict(document.get("data")).get("pb"))
    if root is None:
        return None
    gift = root.get_sub(10)
    gift_name = _clean(gift.get_str(2))
    user = _clean(root.get_str(2))
    if not gift_name or not user:
        return None
    message = _message(MessageKind.GIFT, user)
    message.avatar_url = https_url(root.get_str(3))
    message.timestamp_ms = gift.get_num(10) * 1000
    verb = _clean(gift.get_str(18)) or "投喂"
    icon = _as_dict({})
    del icon
    icon_info = gift.get_sub(35)
    message.parts = [
        Fragment(type="text", text=f"{verb} ", verb=True),
        Fragment(type="emote", text=gift_name, url=https_url(icon_info.get_str(1))),
    ]
    message.count = max(1, gift.get_num(3))
    message.merge_key = f"gift/{gift.get_num(1)}/{gift_name}"
    return message


def _like(document: dict[str, Any]) -> ChatMessage | None:
    data = _as_dict(document.get("data"))
    base = _as_dict(_as_dict(data.get("uinfo")).get("base"))
    user = _clean(data.get("uname")) or _clean(base.get("name"))
    if not user:
        return None
    message = _message(MessageKind.LIKE, user)
    message.avatar_url = https_url(base.get("face"))
    message.parts = [Fragment(type="text", text=_clean(data.get("like_text")) or "为主播点赞了")]
    return message


def _super_chat(document: dict[str, Any]) -> ChatMessage | None:
    data = _as_dict(document.get("data"))
    user = _as_dict(data.get("user_info"))
    message = _message(MessageKind.PAID, _clean(user.get("uname")))
    message.avatar_url = https_url(user.get("face"))
    message.timestamp_ms = _as_int(data.get("start_time")) * 1000
    message.amount_value = max(0, _as_int(data.get("price")))
    message.amount = f"CN¥{message.amount_value}" if message.amount_value else ""
    message.parts = _split_fragments(_clean(data.get("message")), {})
    guard = _guard_level(
        user.get("guard_level"), _as_dict(data.get("medal_info")).get("guard_level")
    )
    if guard >= 3:
        message.user_type = UserType.MEMBER
    message.dwell_ms = dwell_for(message.amount_value)
    return message


def _membership(document: dict[str, Any]) -> ChatMessage | None:
    data = _as_dict(document.get("data"))
    message = _message(MessageKind.MEMBERSHIP, _clean(data.get("username")))
    if not message.user:
        return None
    message.timestamp_ms = _as_int(data.get("start_time")) * 1000
    level = _as_int(data.get("guard_level"))
    label = {1: "总督", 2: "提督", 3: "舰长"}.get(level, "大航海")
    gold = max(0, _as_int(data.get("price")))
    money = f"CN¥{gold // 1000}" if gold else ""
    message.amount = f"{label} · {money}" if money else label
    message.parts = [Fragment(type="text", text=f"开通了{label}", verb=True)]
    if level >= 3:
        message.user_type = UserType.MEMBER
    return message


class EventParser:
    def parse(self, document: dict[str, Any]) -> ChatMessage | None:
        command = _clean(document.get("cmd")).split(":", 1)[0]
        handlers: dict[str, Callable[[dict[str, Any]], ChatMessage | None]] = {
            "DANMU_MSG": _danmu,
            "INTERACT_WORD_V2": _entry,
            "SEND_GIFT_V2": _gift,
            "LIKE_INFO_V3_CLICK": _like,
            "SUPER_CHAT_MESSAGE": _super_chat,
            "GUARD_BUY": _membership,
        }
        handler = handlers.get(command)
        return handler(document) if handler else None


class EventProcessor:
    def __init__(
        self,
        emit: Callable[[ChatMessage], Awaitable[None]],
        entry_merge_seconds: float,
        gift_merge_seconds: float,
    ) -> None:
        self.emit = emit
        self.entry_window = entry_merge_seconds
        self.gift_window = gift_merge_seconds
        self.parser = EventParser()
        self._tasks: set[asyncio.Task[None]] = set()
        self._entry: ChatMessage | None = None
        self._gifts: dict[tuple[str, str, str], ChatMessage] = {}
        self._closed = False

    def _schedule(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def handle(self, document: dict[str, Any]) -> None:
        message = self.parser.parse(document)
        if message is not None and not self._closed:
            await self.submit(message)

    async def submit(self, message: ChatMessage) -> None:
        if message.kind == MessageKind.ENTRY and self.entry_window > 0:
            await self._submit_entry(message)
        elif message.kind == MessageKind.GIFT and self.gift_window > 0:
            await self._submit_gift(message)
        else:
            await self.emit(message)

    def _entry_body(self) -> None:
        if self._entry is None:
            return
        if self._entry.count <= 1:
            text = "进入了直播间"
        else:
            text = f"等 {self._entry.count} 人进入了直播间"
        self._entry.parts = [Fragment(type="text", text=text)]

    async def _submit_entry(self, message: ChatMessage) -> None:
        if self._entry is None:
            self._entry = message
            self._schedule(self._flush_entry_after(self.entry_window))
            return
        self._entry.count += 1
        self._entry.timestamp_ms = message.timestamp_ms or self._entry.timestamp_ms
        self._entry_body()

    async def _flush_entry_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        message, self._entry = self._entry, None
        if message is not None:
            await self.emit(message)

    def _gift_key(self, message: ChatMessage) -> tuple[str, str, str]:
        return message.user, message.avatar_url or "", message.merge_key

    async def _submit_gift(self, message: ChatMessage) -> None:
        key = self._gift_key(message)
        current = self._gifts.get(key)
        if current is not None:
            current.count += message.count
            current.timestamp_ms = message.timestamp_ms or current.timestamp_ms
            return
        self._gifts[key] = message
        self._schedule(self._flush_gift_after(key, self.gift_window))

    async def _flush_gift_after(self, key: tuple[str, str, str], delay: float) -> None:
        await asyncio.sleep(delay)
        message = self._gifts.pop(key, None)
        if message is not None:
            await self.emit(message)

    async def shutdown(self) -> None:
        self._closed = True
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        entry, self._entry = self._entry, None
        if entry is not None:
            await self.emit(entry)
        for message in self._gifts.values():
            await self.emit(message)
        self._gifts.clear()
