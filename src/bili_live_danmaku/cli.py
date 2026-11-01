from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__
from .app import Runtime, create_app
from .bili.client import BiliApi, CookieInvalidError, has_login_cookie
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


async def _validate_cookie(runtime: Runtime) -> str | None:
    cookie = runtime.read_cookie()
    if not has_login_cookie(cookie):
        return None
    api = BiliApi(cookie)
    try:
        try:
            await api.auth_uid()
        except CookieInvalidError as exc:
            return str(exc)
        except Exception as exc:
            return f"无法验证 B站 Cookie：{exc}"
    finally:
        await api.close()
    return None


def _print_cookie_refresh_help(runtime: Runtime, error: str) -> None:
    print(f"\n[ERROR] {error}", file=sys.stderr)
    print("请重新获取 B站 Cookie：", file=sys.stderr)
    print("  uv run tools/get_bili_cookie.py", file=sys.stderr)
    print("\n扫码登录完成后，再重新启动浮层：", file=sys.stderr)
    print("  uv run bili-live-danmaku", file=sys.stderr)
    print(f"\n当前 Cookie 文件：{runtime.cookie_path()}", file=sys.stderr)


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
    if not args.demo:
        cookie_error = asyncio.run(_validate_cookie(runtime))
        if cookie_error is not None:
            _print_cookie_refresh_help(runtime, cookie_error)
            return 1

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
