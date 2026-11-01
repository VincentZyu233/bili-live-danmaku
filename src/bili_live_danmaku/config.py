from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .models import AppConfig

APP_NAME = "bili-live-danmaku"
PROJECT_ROOT_ENV = "BILI_LIVE_DANMAKU_ROOT"


def default_project_root() -> Path:
    override = os.environ.get(PROJECT_ROOT_ENV)
    return Path(override).expanduser().resolve() if override else Path.cwd().resolve()


def legacy_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / APP_NAME).resolve()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class ConfigStore:
    def __init__(self, root_dir: Path | None = None, config_path: Path | None = None) -> None:
        self.root_dir = (root_dir or default_project_root()).expanduser().resolve()
        self.config_dir = self.root_dir / "config"
        self.path = (
            config_path.expanduser().resolve()
            if config_path
            else self.config_dir / "config.yaml"
        )
        self.example_path = self.config_dir / "config.example.yaml"
        self._config: AppConfig | None = None
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self.root_dir / path).resolve()

    @property
    def data_dir(self) -> Path:
        value = self._config.storage.data_dir if self._config else "data"
        return self.resolve_path(value)

    def cookie_path(self, value: str | None = None) -> Path:
        selected = value or (self._config.cookie_file if self._config else "config/cookie.txt")
        return self.resolve_path(selected)

    def load(self) -> AppConfig:
        config: AppConfig | None
        if self.path.exists():
            config = self._read_yaml(self.path)
        else:
            config = self._migrate_legacy() or self._read_example()
            if config is None:
                config = AppConfig()
            self.save(config)
        self._config = config
        return config

    def save(self, config: AppConfig) -> None:
        config = self._with_defaults(config)
        self._config = config
        payload = yaml.safe_dump(
            config.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        )
        atomic_write_text(self.path, payload)

    def _read_example(self) -> AppConfig | None:
        if not self.example_path.is_file():
            return None
        return self._read_yaml(self.example_path)

    def _read_yaml(self, path: Path) -> AppConfig:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if raw is None:
                raw = {}
            if not isinstance(raw, dict):
                raise ValueError("配置根节点必须是对象")
            return self._with_defaults(AppConfig.model_validate(raw))
        except (OSError, ValueError, yaml.YAMLError):
            broken = self.path.with_suffix(".broken.yaml")
            if path == self.path:
                try:
                    self.path.replace(broken)
                except OSError:
                    pass
            config = self._with_defaults(AppConfig())
            self.save(config)
            return config

    def _migrate_legacy(self) -> AppConfig | None:
        legacy = legacy_data_dir()
        config_file = legacy / "config.json"
        if not config_file.is_file():
            return None
        try:
            raw: Any = json.loads(config_file.read_text(encoding="utf-8"))
            config = AppConfig.model_validate(raw)
        except (OSError, ValueError, TypeError):
            return None

        cookie_source = legacy / "cookie.txt"
        if cookie_source.is_file():
            cookie_target = self.root_dir / "config" / "cookie.txt"
            cookie_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cookie_source, cookie_target)

        target_data = self.root_dir / "data"
        for name in ("history", "fonts", "cache"):
            source = legacy / name
            if source.is_dir():
                shutil.copytree(source, target_data / name, dirs_exist_ok=True)

        config.version = 2
        config.cookie_file = "config/cookie.txt"
        config.storage.data_dir = "data"
        return self._with_defaults(config)

    def _with_defaults(self, config: AppConfig) -> AppConfig:
        if not config.cookie_file:
            config.cookie_file = "config/cookie.txt"
        if not config.storage.data_dir:
            config.storage.data_dir = "data"
        return config
