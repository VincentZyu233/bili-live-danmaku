from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from bili_live_danmaku.app import Runtime, create_app, demo_messages
from bili_live_danmaku.config import ConfigStore


def test_api_and_pages_smoke(tmp_path: Path) -> None:
    runtime = Runtime(ConfigStore(tmp_path), demo=True)
    app = create_app(runtime)
    with TestClient(app) as client:
        assert client.get("/admin").status_code == 200
        assert client.get("/overlay").status_code == 200
        assert "Bili Live Danmaku" in client.get("/admin").text

        config = client.get("/api/config").json()
        config["auto_connect"] = False
        config["history_lines"] = 12
        response = client.put("/api/config", json=config)
        assert response.status_code == 200
        assert response.json()["history_lines"] == 12

        response = client.post("/api/cookie", json={"cookie": "SESSDATA=abc; DedeUserID=1"})
        assert response.status_code == 200
        assert (tmp_path / "cookie.txt").read_text(encoding="utf-8").startswith("SESSDATA=")

        response = client.post(
            "/api/fonts", files={"file": ("demo.ttf", b"not-a-real-font", "font/ttf")}
        )
        assert response.status_code == 200
        assert response.json()["url"].startswith("/fonts/")

        with client.websocket_connect("/ws") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["type"] == "snapshot"
            assert "config" in snapshot["payload"]


def test_status_never_returns_cookie_value(tmp_path: Path) -> None:
    runtime = Runtime(ConfigStore(tmp_path), cookie_override="SESSDATA=top-secret; DedeUserID=1")
    app = create_app(runtime)
    with TestClient(app) as client:
        text = client.get("/api/status").text
        assert "top-secret" not in text
        assert client.get("/api/status").json()["cookie_present"] is True


def test_demo_messages_include_local_avatars_and_varied_kinds() -> None:
    messages = demo_messages()
    assert len(messages) == 10
    assert all(
        message.avatar_url and message.avatar_url.startswith("/static/avatars/")
        for message in messages
    )
    assert len({message.kind for message in messages}) >= 5
