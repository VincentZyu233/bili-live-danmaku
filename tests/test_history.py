from __future__ import annotations

from pathlib import Path

from bili_live_danmaku.history import HistoryStore
from bili_live_danmaku.models import ChatMessage, Fragment, MessageKind


def _message(index: int, kind: MessageKind = MessageKind.TEXT) -> ChatMessage:
    return ChatMessage(
        id=str(index),
        kind=kind,
        user=f"user-{index}",
        parts=[Fragment(type="text", text=f"message-{index}")],
    )


async def test_history_round_trip_and_window(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    store.select_room(123, 2)
    store.append_current(_message(1))
    store.append_current(_message(2))
    store.append_current(_message(3))
    await store.flush()
    loaded = await store.load(123, 10)
    assert [message.id for message in loaded] == ["2", "3"]


async def test_paid_messages_are_not_saved(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    store.select_room(456, 10)
    store.append_current(_message(1, MessageKind.PAID))
    await store.flush()
    assert await store.load(456, 10) == []
