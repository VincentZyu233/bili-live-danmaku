#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["websocket-client>=1.7"]
# ///
"""Open a browser, wait for Bilibili login, then write the Cookie file.

This is a cross-platform adaptation of the helper in VincentZyu233's upstream
pw-live-danmaku pull request. It uses a temporary browser profile and Chrome
DevTools Protocol, so it never touches the normal browser profile or handles a
password.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import websocket
except ImportError:
    print("缺少 websocket-client，请用 uv 运行：uv run tools/get_bili_cookie.py", file=sys.stderr)
    raise SystemExit(1) from None


LOGIN_URL = "https://passport.bilibili.com/login"
REQUIRED_COOKIES = {"SESSDATA", "bili_jct", "DedeUserID"}
COOKIE_ORDER = ["SESSDATA", "bili_jct", "DedeUserID", "buvid3", "buvid4", "b_nut"]


def default_output() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "bili-live-danmaku" / "cookie.txt"


def browser_candidates() -> list[Path]:
    candidates: list[Path] = []
    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    local = os.environ.get("LOCALAPPDATA")
    for root in program_files:
        if not root:
            continue
        base = Path(root)
        candidates.extend(
            [
                base / "Microsoft/Edge/Application/msedge.exe",
                base / "Google/Chrome/Application/chrome.exe",
                base / "BraveSoftware/Brave-Browser/Application/brave.exe",
                base / "Chromium/Application/chrome.exe",
            ]
        )
    if local:
        base = Path(local)
        candidates.extend(
            [
                base / "Microsoft/Edge/Application/msedge.exe",
                base / "Google/Chrome/Application/chrome.exe",
                base / "BraveSoftware/Brave-Browser/Application/brave.exe",
            ]
        )
    for name in ("msedge", "chrome", "chromium", "brave", "google-chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return candidates


def find_browser(value: str | None) -> Path:
    if value:
        candidate = Path(value).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        found = shutil.which(value)
        if found:
            return Path(found)
        raise FileNotFoundError(f"找不到浏览器：{value}")
    for candidate in browser_candidates():
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("没有找到 Edge、Chrome、Chromium 或 Brave，请用 --browser-path 指定")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fetch_json(url: str, timeout: float = 1.0) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def wait_for_page(port: int, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            pages = fetch_json(f"http://127.0.0.1:{port}/json/list")
            if isinstance(pages, list):
                candidates = [
                    page
                    for page in pages
                    if isinstance(page, dict)
                    and page.get("type") == "page"
                    and page.get("webSocketDebuggerUrl")
                ]
                for page in candidates:
                    if "bilibili.com" in str(page.get("url", "")):
                        return str(page["webSocketDebuggerUrl"])
                if candidates:
                    return str(candidates[0]["webSocketDebuggerUrl"])
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"浏览器调试端口没有就绪：{last_error}")


class CDP:
    def __init__(self, websocket_url: str) -> None:
        self.websocket = websocket.create_connection(
            websocket_url, timeout=5, origin="http://127.0.0.1"
        )
        self.next_id = 0

    def call(self, method: str, **params: object) -> dict[str, object]:
        self.next_id += 1
        request_id = self.next_id
        self.websocket.send(json.dumps({"id": request_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.websocket.recv())
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                raise RuntimeError(f"CDP {method} 失败：{error}")
            result = message.get("result", {})
            return result if isinstance(result, dict) else {}

    def close(self) -> None:
        try:
            self.websocket.close()
        except Exception:
            pass


def bilibili_cookies(cookies: object) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(cookies, list):
        return result
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get("domain", "")).lstrip(".").lower()
        name = str(cookie.get("name", ""))
        if (domain == "bilibili.com" or domain.endswith(".bilibili.com")) and name:
            result[name] = str(cookie.get("value", ""))
    return result


def format_cookie(cookies: dict[str, str]) -> str:
    names = [name for name in COOKIE_ORDER if name in cookies]
    names.extend(name for name in sorted(cookies) if name not in names and name in REQUIRED_COOKIES)
    return "; ".join(f"{name}={cookies[name]}" for name in names)


def write_cookie(path: Path, cookie: str) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(cookie, encoding="utf-8", newline="\n")
    os.replace(temporary, target)
    if os.name != "nt":
        os.chmod(target, 0o600)


def cookie_is_logged_in(cookie: str) -> bool:
    request = urllib.request.Request(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.bilibili.com/",
            "Cookie": cookie,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return False
    data = payload.get("data") if isinstance(payload, dict) else None
    return isinstance(data, dict) and data.get("isLogin") is True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="打开浏览器扫码登录 B站并导出 Cookie")
    parser.add_argument("--browser-path", help="Edge/Chrome/Chromium 可执行文件路径")
    parser.add_argument("--output", type=Path, default=default_output(), help="Cookie 输出路径")
    parser.add_argument("--timeout", type=float, default=300, help="等待登录秒数，默认 300")
    parser.add_argument("--keep-open", action="store_true", help="拿到 Cookie 后保持浏览器打开")
    parser.add_argument("--profile-dir", type=Path, help="复用指定浏览器 profile")
    parser.add_argument("--keep-profile", action="store_true", help="退出后保留临时 profile")
    parser.add_argument(
        "--print-cookie", action="store_true", help="在终端打印完整 Cookie（不推荐）"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        print("--timeout 必须大于 0", file=sys.stderr)
        return 2
    try:
        browser = find_browser(args.browser_path)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    profile = (
        args.profile_dir.expanduser().resolve()
        if args.profile_dir
        else Path(tempfile.mkdtemp(prefix="bili-live-danmaku-cookie-"))
    )
    profile.mkdir(parents=True, exist_ok=True)
    if args.profile_dir:
        args.keep_profile = True

    port = free_port()
    command = [
        str(browser),
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        LOGIN_URL,
    ]
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    cdp: CDP | None = None
    cookie: str | None = None
    print(f"浏览器：{browser}")
    print(f"临时 profile：{profile}")
    print("请在打开的浏览器里扫码登录 B站；登录完成后脚本会自动继续。")

    try:
        cdp = CDP(wait_for_page(port, min(30, args.timeout)))
        cdp.call("Network.enable")
        deadline = time.monotonic() + args.timeout
        last_status = 0.0
        while time.monotonic() < deadline:
            result = cdp.call("Network.getAllCookies")
            cookies = bilibili_cookies(result.get("cookies", []))
            missing = REQUIRED_COOKIES - cookies.keys()
            if not missing:
                candidate = format_cookie(cookies)
                if cookie_is_logged_in(candidate):
                    cookie = candidate
                    break
            now = time.monotonic()
            if now - last_status >= 2:
                if missing:
                    print(f"等待登录，还缺少：{', '.join(sorted(missing))}")
                else:
                    print("已检测到 Cookie，等待 B站确认登录状态...")
                last_status = now
            time.sleep(0.5)
        if not cookie:
            raise TimeoutError("等待登录超时，没有拿到完整 Cookie")
        write_cookie(args.output, cookie)
        print(f"\nCookie 已写入：{args.output.expanduser().resolve()}")
        print("已配置字段：", ", ".join(part.split("=", 1)[0] for part in cookie.split("; ")))
        if args.print_cookie:
            print(cookie)
        else:
            print("为安全起见未在终端打印完整 Cookie。")
        print("\n启动浮层：")
        print(f'  uv run bili-live-danmaku --cookie-file "{args.output.expanduser().resolve()}"')
    except (RuntimeError, TimeoutError, OSError, ValueError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if cdp and not args.keep_open:
            try:
                cdp.call("Browser.close")
            except Exception:
                pass
        if cdp:
            cdp.close()
        if not args.keep_open:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        if not args.keep_profile:
            shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
