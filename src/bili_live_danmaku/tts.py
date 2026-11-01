from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Generator
from pathlib import Path
from typing import Any

from .models import ChatMessage, MessageKind, TTSSettings

logger = logging.getLogger(__name__)


def _amount_text(amount: str) -> str:
    cleaned = amount.rsplit("·", 1)[-1].replace("CN¥", "").replace("¥", "").strip()
    return f"，金额 {cleaned} 元" if cleaned else ""


def _spoken_body(message: ChatMessage, body: str) -> str:
    if message.kind is MessageKind.TEXT:
        return f"{message.user}说：{body}" if message.user else body
    if message.kind is MessageKind.GIFT:
        phrase = (
            f"{message.user}{body}" if body.startswith("投喂") else f"{message.user}送出了{body}"
        )
    elif message.kind is MessageKind.ENTRY:
        phrase = f"{message.user}{body}" if "进入" in body else f"{message.user}进入了直播间"
    elif message.kind is MessageKind.LIKE:
        phrase = f"{message.user}{body}" if "点赞" in body else f"{message.user}为主播点赞了"
    elif message.kind is MessageKind.PAID:
        phrase = f"{message.user}发送了一条醒目留言：{body}"
        phrase += _amount_text(message.amount)
    elif message.kind is MessageKind.MEMBERSHIP:
        phrase = f"{message.user}{body}" if body else f"{message.user}开通了舰长"
        phrase += _amount_text(message.amount)
    else:
        phrase = f"{message.user}：{body}" if message.user else body
    if message.count > 1:
        phrase += f"，共 {message.count} 次"
    return phrase


def message_to_speech(message: ChatMessage, include_username: bool, max_chars: int) -> str | None:
    text_parts = [
        fragment.text.strip()
        for fragment in message.parts
        if fragment.text.strip()
    ]
    body = " ".join(text_parts).strip()
    if not body and not message.amount:
        return None
    text = _spoken_body(message, body) if include_username else body
    return text[:max_chars].strip() or None


def _pcm_chunks(decoded: Any) -> Generator[bytes, int, None]:
    raw = decoded.samples.tobytes()
    bytes_per_frame = max(1, decoded.nchannels * decoded.sample_width)
    offset = 0
    frame_count = yield b""
    while offset < len(raw):
        chunk_size = max(1, frame_count) * bytes_per_frame
        chunk = raw[offset : offset + chunk_size]
        offset += len(chunk)
        frame_count = yield chunk


def _play_audio_file(path: Path) -> None:
    import miniaudio

    decoded = miniaudio.decode_file(str(path))
    device = miniaudio.PlaybackDevice()
    try:
        stream = _pcm_chunks(decoded)
        next(stream)
        device.start(stream)
        duration = len(decoded.samples) / max(1, decoded.sample_rate * decoded.nchannels)
        time.sleep(duration + 0.08)
    finally:
        device.close()


class TTSService:
    def __init__(self, settings: TTSSettings, cache_dir: Path) -> None:
        self.settings = settings
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.queue_size)
        self._task: asyncio.Task[None] | None = None
        self._seen: deque[str] = deque(maxlen=512)
        self._seen_set: set[str] = set()

    async def start(self) -> None:
        if not self.settings.enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="edge-tts")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def enqueue(self, message: ChatMessage) -> None:
        if not self.settings.enabled or message.kind not in self.settings.read_kinds:
            return
        if message.id in self._seen_set:
            return
        text = message_to_speech(
            message,
            include_username=self.settings.include_username,
            max_chars=self.settings.max_chars,
        )
        if not text:
            return
        self._remember(message.id)
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(text)

    def _remember(self, message_id: str) -> None:
        if len(self._seen) == self._seen.maxlen:
            oldest = self._seen[0]
            self._seen_set.discard(oldest)
        self._seen.append(message_id)
        self._seen_set.add(message_id)

    async def speak_test(self, text: str = "弹幕朗读测试成功") -> None:
        await self._speak(text)

    async def _run(self) -> None:
        while True:
            text = await self.queue.get()
            try:
                await self._speak(text)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Edge TTS 朗读失败")
            finally:
                self.queue.task_done()
            if self.settings.min_interval_ms:
                await asyncio.sleep(self.settings.min_interval_ms / 1000)

    async def _speak(self, text: str) -> None:
        import edge_tts

        audio_path = self.cache_dir / f"tts-{uuid.uuid4().hex}.mp3"
        try:
            communicate = edge_tts.Communicate(
                text,
                self.settings.voice,
                rate=self.settings.rate,
                volume=self.settings.volume,
                pitch=self.settings.pitch,
            )
            await communicate.save(str(audio_path))
            await asyncio.to_thread(_play_audio_file, audio_path)
        finally:
            try:
                audio_path.unlink()
            except FileNotFoundError:
                pass
