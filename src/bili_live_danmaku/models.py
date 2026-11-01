from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class MessageKind(StrEnum):
    TEXT = "text"
    GIFT = "gift"
    ENTRY = "entry"
    LIKE = "like"
    PAID = "paid"
    MEMBERSHIP = "membership"


class UserType(StrEnum):
    NORMAL = "normal"
    MEMBER = "member"
    MODERATOR = "moderator"
    OWNER = "owner"


class Fragment(BaseModel):
    type: Literal["text", "emote"] = "text"
    text: str = ""
    url: str | None = None
    px: int = 0
    verb: bool = False


class ChatMessage(BaseModel):
    id: str
    kind: MessageKind
    user_type: UserType = UserType.NORMAL
    user: str = ""
    user_color: str | None = None
    avatar_url: str | None = None
    parts: list[Fragment] = Field(default_factory=list)
    amount: str = ""
    amount_value: int = 0
    count: int = 1
    timestamp_ms: int = 0
    merge_key: str = ""
    dwell_ms: int = 0


class ConnectionStatus(BaseModel):
    state: Literal["idle", "connecting", "connected", "reconnecting", "error"] = "idle"
    message: str = "尚未连接"
    room_id: int | None = None
    real_room_id: int | None = None
    cookie_present: bool = False
    message_rate: float = 0.0
    last_error: str | None = None


class FontSettings(BaseModel):
    family: str = "LXGW WenKai Mono"
    size: int = Field(default=28, ge=12, le=72)
    url: str | None = None


class ThemeSettings(BaseModel):
    width: int = Field(default=480, ge=240, le=1920)
    height: int = Field(default=1080, ge=240, le=1920)
    font: FontSettings = Field(default_factory=FontSettings)
    panel_background: str = "#0b0d12"
    panel_opacity: float = Field(default=0.58, ge=0, le=1)
    panel_radius: int = Field(default=28, ge=0, le=80)
    panel_border: str = "#ffffff"
    panel_border_opacity: float = Field(default=0.12, ge=0, le=1)
    panel_padding: int = Field(default=18, ge=0, le=64)
    row_gap: int = Field(default=8, ge=0, le=32)
    text_color: str = "#f4f6fb"
    muted_color: str = "#aeb5c2"
    accent_color: str = "#ffd66b"
    show_status: bool = True
    max_messages: int = Field(default=80, ge=5, le=500)


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=6161, ge=1, le=65535)
    open_browser: bool = True


class StorageSettings(BaseModel):
    data_dir: str = "data"


class ReconnectSettings(BaseModel):
    base_seconds: float = Field(default=1.0, ge=0.1, le=60)
    max_seconds: float = Field(default=30.0, ge=1, le=300)


class TTSSettings(BaseModel):
    enabled: bool = False
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    read_kinds: list[MessageKind] = Field(default_factory=lambda: list(MessageKind))
    include_username: bool = True
    max_chars: int = Field(default=180, ge=1, le=1000)
    queue_size: int = Field(default=32, ge=1, le=500)
    min_interval_ms: int = Field(default=300, ge=0, le=10_000)


class LoggingSettings(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class AppConfig(BaseModel):
    version: int = 2
    room: str = ""
    cookie_file: str = "config/cookie.txt"
    history_lines: int = Field(default=60, ge=0, le=2000)
    entry_merge_seconds: float = Field(default=5.0, ge=0, le=60)
    gift_merge_seconds: float = Field(default=5.0, ge=0, le=60)
    auto_connect: bool = True
    server: ServerSettings = Field(default_factory=ServerSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    reconnect: ReconnectSettings = Field(default_factory=ReconnectSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    theme: ThemeSettings = Field(default_factory=ThemeSettings)


class EventEnvelope(BaseModel):
    type: Literal["event", "history", "status", "config", "snapshot", "clear"]
    sequence: int
    server_time_ms: int
    payload: object
