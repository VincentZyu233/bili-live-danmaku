from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .config import atomic_write_text
from .models import ChatMessage


class HistoryStore:
    def __init__(self, data_dir: Path) -> None:
        self.directory = data_dir / "history"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._cached: dict[str, ChatMessage] = {}
        self._save_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._room: int | None = None
        self._lines = 0

    def path_for(self, room_id: int) -> Path:
        return self.directory / f"{room_id}.json"

    async def load(self, room_id: int, limit: int) -> list[ChatMessage]:
        if limit <= 0:
            return []
        path = self.path_for(room_id)
        try:
            raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
            items = json.loads(raw)
            if not isinstance(items, list):
                return []
            return [ChatMessage.model_validate(item) for item in items[-limit:]]
        except (OSError, ValueError, TypeError):
            return []

    def select_room(self, room_id: int, lines: int) -> None:
        if self._room != room_id:
            self._cached.clear()
            self._room = room_id
        self._lines = lines

    def append_current(self, message: ChatMessage) -> None:
        if self._room is None or self._lines <= 0 or message.kind.value == "paid":
            return
        self._cached[message.id] = message
        while len(self._cached) > self._lines:
            self._cached.pop(next(iter(self._cached)))
        if self._save_task is None or self._save_task.done():
            self._save_task = asyncio.create_task(self._save_soon())

    async def _save_soon(self) -> None:
        await asyncio.sleep(0.8)
        async with self._lock:
            room = self._room
            if room is None or self._lines <= 0:
                return
            items = list(self._cached.values())[-self._lines :]
            payload = json.dumps(
                [item.model_dump(mode="json") for item in items],
                ensure_ascii=False,
                indent=2,
            )
            await asyncio.to_thread(atomic_write_text, self.path_for(room), payload + "\n")

    async def flush(self) -> None:
        if self._save_task is not None and not self._save_task.done():
            await self._save_task
