from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__
from .app import Runtime, create_app
from .config import ConfigStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bili-live-danmaku",
        description="把 B 站直播弹幕渲染成适用于 OBS 的透明网页浮层。",
    )
    parser.add_argument("--room", help="直播间号或 live.bilibili.com 地址")
    cookie_group = parser.add_mutually_exclusive_group()
    cookie_group.add_argument("--cookie", help="直接传入 Cookie；会出现在进程参数中，不推荐")
    cookie_group.add_argument("--cookie-file", help="从文件读取 Cookie")
    parser.add_argument("--data-dir", help="覆盖应用数据目录")
    parser.add_argument("--port", type=int, default=6161, help="本地 WebUI 端口，默认 6161")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开控制台")
    parser.add_argument("--demo", action="store_true", help="循环发送演示消息，不连接B站")
    parser.add_argument("--verbose", action="store_true", help="输出详细服务日志")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _open_browser_later(port: int) -> None:
    timer = threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}/admin"))
    timer.daemon = True
    timer.start()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port 必须在 1 到 65535 之间")
    if args.cookie:
        print("警告：--cookie 会出现在本机进程参数中，建议改用 --cookie-file。")

    data_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else None
    store = ConfigStore(data_dir)
    runtime = Runtime(
        store,
        cookie_override=args.cookie,
        cookie_file_override=args.cookie_file,
        demo=args.demo,
    )
    if args.room:
        runtime.config.room = args.room

    app = create_app(runtime)
    if not args.no_browser:
        _open_browser_later(args.port)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="info" if args.verbose else "warning",
        access_log=args.verbose,
    )
    return 0
