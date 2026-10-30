from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import AppConfig

APP_NAME = "bili-live-danmaku"


def default_data_dir() -> Path:
    override = os.environ.get("BILI_LIVE_DANMAKU_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / APP_NAME).resolve()


def default_cookie_file(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "cookie.txt"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class ConfigStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = (data_dir or default_data_dir()).resolve()
        self.path = self.data_dir / "config.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppConfig:
        if not self.path.exists():
            config = self._with_defaults(AppConfig())
            self.save(config)
            return config
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return self._with_defaults(AppConfig.model_validate(raw))
        except (OSError, ValueError):
            broken = self.path.with_suffix(".broken.json")
            try:
                self.path.replace(broken)
            except OSError:
                pass
            config = self._with_defaults(AppConfig())
            self.save(config)
            return config

    def save(self, config: AppConfig) -> None:
        config = self._with_defaults(config)
        atomic_write_text(self.path, config.model_dump_json(indent=2) + "\n")

    def _with_defaults(self, config: AppConfig) -> AppConfig:
        if not config.cookie_file:
            config.cookie_file = str(default_cookie_file(self.data_dir))
        return config
