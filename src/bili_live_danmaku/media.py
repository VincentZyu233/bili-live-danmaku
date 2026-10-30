from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_FONT_BYTES = 64 * 1024 * 1024
IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
}
CONTENT_TYPES = {extension: content_type for content_type, extension in IMAGE_TYPES.items()}
ALLOWED_IMAGE_HOSTS = (
    "hdslb.com",
    "bilibili.com",
    "biliimg.com",
    "bilivideo.com",
)
FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2", ".ttc"}


def _allowed_image_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == root or host.endswith(f".{root}") for root in ALLOWED_IMAGE_HOSTS)


class ImageProxy:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
                    "Gecko/20100101 Firefox/133.0"
                ),
                "Referer": "https://live.bilibili.com/",
                "Origin": "https://live.bilibili.com",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def get(self, url: str) -> tuple[Path, str]:
        if not _allowed_image_url(url):
            raise ValueError("不允许代理这个图片地址")
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        for extension, content_type in CONTENT_TYPES.items():
            cached = self.cache_dir / f"{key}{extension}"
            if cached.exists():
                return cached, content_type

        async with self.client.stream("GET", url) as response:
            response.raise_for_status()
            if not _allowed_image_url(str(response.url)):
                raise ValueError("图片重定向到了不允许的域名")
            content_type = (
                response.headers.get("content-type", "") or ""
            ).split(";", 1)[0].lower()
            suffix = IMAGE_TYPES.get(content_type)
            if suffix is None:
                raise ValueError("远程资源不是受支持的图片格式")
            length = response.headers.get("content-length")
            if length and int(length) > MAX_IMAGE_BYTES:
                raise ValueError("图片超过大小限制")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise ValueError("图片超过大小限制")
                chunks.append(chunk)

        target = self.cache_dir / f"{key}{suffix}"
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(b"".join(chunks))
        temporary.replace(target)
        return target, content_type


class FontLibrary:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, filename: str, data: bytes) -> dict[str, str]:
        extension = Path(filename).suffix.lower()
        if extension not in FONT_EXTENSIONS:
            raise ValueError("只支持 TTF、OTF、TTC、WOFF 和 WOFF2 字体")
        if len(data) > MAX_FONT_BYTES:
            raise ValueError("字体文件超过 64 MB 限制")
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(filename).stem).strip("-") or "custom-font"
        stored = f"{stem}-{uuid.uuid4().hex[:8]}{extension}"
        (self.directory / stored).write_bytes(data)
        family = f"Bili Live {Path(stored).stem}"
        return {"family": family, "url": f"/fonts/{stored}", "filename": filename, "stored": stored}

    def resolve(self, name: str) -> Path | None:
        if Path(name).name != name:
            return None
        candidate = self.directory / name
        return candidate if candidate.is_file() else None

    def uploaded(self) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for path in sorted(self.directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in FONT_EXTENSIONS:
                continue
            family = f"Bili Live {path.stem}"
            result.append(
                {"name": path.name, "family": family, "url": f"/fonts/{path.name}"}
            )
        return result


    def system_fonts(self) -> list[str]:
        try:
            import winreg
        except ImportError:
            return ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"]
        names: set[str] = set()
        key_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, key_path) as key:
                    index = 0
                    while True:
                        try:
                            name, _value, _kind = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        display = re.sub(
                            r"\s+\((TrueType|OpenType|All Res|PostScript)\)$", "", name
                        )
                        display = re.sub(r"\.(ttf|otf|ttc)$", "", display, flags=re.IGNORECASE)
                        if display:
                            names.add(display)
                        lowered = display.lower()
                        if "lxgwwenkaimono" in lowered:
                            names.add("LXGW WenKai Mono")
                        elif "lxgwwenkai" in lowered:
                            names.add("LXGW WenKai")
                        index += 1
            except OSError:
                continue
        return sorted(names, key=str.casefold)
