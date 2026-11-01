from __future__ import annotations

import json
import shutil
from pathlib import Path

from bili_live_danmaku.config import ConfigStore
from bili_live_danmaku.models import AppConfig


def test_default_config_uses_local_cookie_file(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path)
    config = store.load()
    assert Path(config.cookie_file) == Path("config/cookie.txt")
    assert store.cookie_path() == tmp_path / "config" / "cookie.txt"
    assert store.data_dir == tmp_path / "data"
    assert store.path == tmp_path / "config" / "config.yaml"
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
    assert store.path.with_suffix(".broken.yaml").exists()


def test_example_config_is_copied_to_local_yaml(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    source = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"
    shutil.copy2(source, tmp_path / "config" / "config.example.yaml")
    store = ConfigStore(tmp_path)
    loaded = store.load()
    assert loaded.version == 2
    assert store.path.exists()
    assert store.cookie_path() == tmp_path / "config" / "cookie.txt"


def test_legacy_appdata_is_migrated(tmp_path: Path, monkeypatch) -> None:
    legacy_base = tmp_path / "legacy"
    legacy = legacy_base / "bili-live-danmaku"
    (legacy / "history").mkdir(parents=True)
    (legacy / "history" / "123.json").write_text("[]", encoding="utf-8")
    (legacy / "cookie.txt").write_text("SESSDATA=abc; DedeUserID=1", encoding="utf-8")
    (legacy / "config.json").write_text(json.dumps({"room": "123"}), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(legacy_base))

    store = ConfigStore(tmp_path / "project")
    loaded = store.load()
    assert loaded.room == "123"
    assert store.cookie_path().read_text(encoding="utf-8").startswith("SESSDATA=")
    assert (store.data_dir / "history" / "123.json").exists()
