from __future__ import annotations

from pathlib import Path

from bili_live_danmaku.config import ConfigStore
from bili_live_danmaku.models import AppConfig


def test_default_config_uses_local_cookie_file(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path)
    config = store.load()
    assert Path(config.cookie_file) == tmp_path / "cookie.txt"
    assert store.path.exists()


def test_config_round_trip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path)
    config = AppConfig(room="123", history_lines=3)
    config.theme.panel_radius = 42
    store.save(config)
    loaded = store.load()
    assert loaded.room == "123"
    assert loaded.history_lines == 3
    assert loaded.theme.panel_radius == 42


def test_broken_config_is_replaced(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path)
    store.path.write_text("{not-json", encoding="utf-8")
    loaded = store.load()
    assert loaded.room == ""
    assert store.path.with_suffix(".broken.json").exists()
