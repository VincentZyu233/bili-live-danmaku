from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import tempfile
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .models import AppConfig

APP_NAME = "bili-live-danmaku"
PROJECT_ROOT_ENV = "BILI_LIVE_DANMAKU_ROOT"
CONFIG_VERSION = 3


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


def _yaml_round_trip() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.default_flow_style = False
    return yaml


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
        self._yaml_document: CommentedMap | None = None
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
        if self.path.exists():
            try:
                config, document, source_version = self._read_document(self.path)
            except (OSError, ValueError, ValidationError):
                broken = self.path.with_suffix(".broken.yaml")
                try:
                    self.path.replace(broken)
                except OSError:
                    pass
                config = self._with_defaults(AppConfig())
                document = CommentedMap()
                source_version = CONFIG_VERSION
            self._config = config
            self._yaml_document = document
            if source_version < CONFIG_VERSION:
                self.save(config)
            return config

        migrated = self._migrate_legacy()
        document = CommentedMap()
        if migrated is None:
            example = self._read_example_document()
            if example is None:
                config = self._with_defaults(AppConfig())
            else:
                config, document = example
        else:
            config = migrated
        self._config = config
        self._yaml_document = document
        self.save(config)
        return config

    def reload_from_disk(self) -> AppConfig:
        if not self.path.is_file():
            raise ValueError(f"配置文件不存在：{self.path}")
        config, document, source_version = self._read_document(self.path)
        self._config = config
        self._yaml_document = document
        if source_version < CONFIG_VERSION:
            self.save(config)
        return config

    def save(self, config: AppConfig) -> None:
        config = self._with_defaults(config)
        document = (
            copy.deepcopy(self._yaml_document)
            if self._yaml_document is not None
            else CommentedMap()
        )
        self._sync_mapping(document, config.model_dump(mode="json"))
        self._save_document(config, document)

    def save_yaml_text(self, text: str) -> AppConfig:
        config, document = self.parse_document(text)
        self._save_document(config, document)
        return config

    def validate_yaml_text(self, text: str) -> AppConfig:
        config, _document = self.parse_document(text)
        return config

    def render_yaml(self, config: AppConfig) -> str:
        config = self._with_defaults(config)
        document = (
            copy.deepcopy(self._yaml_document)
            if self._yaml_document is not None
            else CommentedMap()
        )
        self._sync_mapping(document, config.model_dump(mode="json"))
        return self._dump_document(document)

    def current_yaml_text(self) -> str:
        if self.path.is_file():
            return self.path.read_text(encoding="utf-8")
        if self._config is None:
            raise ValueError("配置尚未加载")
        return self.render_yaml(self._config)

    def example_yaml_text(self) -> str | None:
        if not self.example_path.is_file():
            return None
        return self.example_path.read_text(encoding="utf-8")

    def current_revision(self) -> str:
        if not self.path.is_file():
            return "missing"
        data = self.path.read_bytes()
        stat = self.path.stat()
        digest = hashlib.sha256(data).hexdigest()[:12]
        return f"{stat.st_mtime_ns:x}-{digest}"

    def parse_document(self, text: str) -> tuple[AppConfig, CommentedMap]:
        yaml = _yaml_round_trip()
        try:
            raw = yaml.load(text)
        except Exception as exc:
            raise ValueError(f"YAML 解析失败：{exc}") from exc
        if raw is None:
            raw = CommentedMap()
        if not isinstance(raw, MutableMapping):
            raise ValueError("配置根节点必须是对象")
        source_version = self._source_version(raw)
        config = self._with_defaults(AppConfig.model_validate(raw))
        if source_version < CONFIG_VERSION:
            config.version = CONFIG_VERSION
        document = cast(CommentedMap, copy.deepcopy(raw))
        self._sync_mapping(document, config.model_dump(mode="json"))
        return config, document

    def _read_document(self, path: Path) -> tuple[AppConfig, CommentedMap, int]:
        text = path.read_text(encoding="utf-8")
        yaml = _yaml_round_trip()
        try:
            raw = yaml.load(text)
        except Exception as exc:
            raise ValueError(f"YAML 解析失败：{exc}") from exc
        if raw is None:
            raw = CommentedMap()
        if not isinstance(raw, MutableMapping):
            raise ValueError("配置根节点必须是对象")
        source_version = self._source_version(raw)
        config = self._with_defaults(AppConfig.model_validate(raw))
        if source_version < CONFIG_VERSION:
            config.version = CONFIG_VERSION
        document = cast(CommentedMap, copy.deepcopy(raw))
        self._sync_mapping(document, config.model_dump(mode="json"))
        return config, document, source_version

    def _read_example_document(self) -> tuple[AppConfig, CommentedMap] | None:
        if not self.example_path.is_file():
            return None
        try:
            config, document, _source_version = self._read_document(self.example_path)
        except (OSError, ValueError, ValidationError):
            return None
        return config, document

    def _save_document(self, config: AppConfig, document: CommentedMap) -> None:
        self._config = config
        self._yaml_document = document
        atomic_write_text(self.path, self._dump_document(document))

    def _dump_document(self, document: CommentedMap) -> str:
        stream = io.StringIO()
        _yaml_round_trip().dump(document, stream)
        return stream.getvalue()

    @staticmethod
    def _source_version(raw: MutableMapping[str, Any]) -> int:
        value = raw.get("version", 0)
        return value if isinstance(value, int) else 0

    @classmethod
    def _sync_mapping(cls, target: MutableMapping[str, Any], values: dict[str, Any]) -> None:
        for key, value in values.items():
            if isinstance(value, dict):
                child = target.get(key)
                if not isinstance(child, MutableMapping):
                    child = CommentedMap()
                    target[key] = child
                cls._sync_mapping(child, value)
            else:
                target[key] = value
        for key in tuple(target):
            if key not in values:
                del target[key]

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

        config.version = CONFIG_VERSION
        config.cookie_file = "config/cookie.txt"
        config.storage.data_dir = "data"
        return self._with_defaults(config)

    def _with_defaults(self, config: AppConfig) -> AppConfig:
        config.version = CONFIG_VERSION
        if not config.cookie_file:
            config.cookie_file = "config/cookie.txt"
        if not config.storage.data_dir:
            config.storage.data_dir = "data"
        return config
