"""Best-effort build-time company-logo cache for the static public site."""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from typing import Callable, Iterable


LOGO_URL = "https://financialmodelingprep.com/image-stock/{symbol}.png"
SYMBOL = re.compile(r"^[A-Z0-9.-]{1,15}$")
MAX_BYTES = 2_000_000
EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


def fetch_logo(url: str, timeout: int) -> tuple[int, str, bytes]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "invest-ai-site/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return (int(response.status), response.headers.get_content_type(),
                response.read(MAX_BYTES + 1))


def valid_image(content_type: str, payload: bytes) -> bool:
    if not 64 <= len(payload) <= MAX_BYTES:
        return False
    if content_type == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if content_type == "image/gif":
        return payload.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"
    return False


def _cached(symbol: str, logo_dir: Path) -> Path | None:
    for extension in EXTENSIONS.values():
        candidate = logo_dir / f"{symbol}.{extension}"
        if not candidate.exists():
            continue
        content_type = next(k for k, v in EXTENSIONS.items() if v == extension)
        try:
            if valid_image(content_type, candidate.read_bytes()):
                return candidate
        except OSError:
            pass
    return None


def _sync_one(symbol: str, root: Path, *, fetch: Callable) -> str | None:
    if not SYMBOL.fullmatch(symbol):
        return None
    logo_dir = root / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    cached = _cached(symbol, logo_dir)
    if cached:
        return f"logos/{cached.name}"
    try:
        status, content_type, payload = fetch(LOGO_URL.format(symbol=symbol), 10)
        if status != 200 or not valid_image(content_type, payload):
            return None
        extension = EXTENSIONS[content_type]
        target = logo_dir / f"{symbol}.{extension}"
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(target)
        return f"logos/{target.name}"
    except (OSError, ValueError, KeyError):
        return None


def sync(symbols: Iterable[str], root: Path,
         *, fetch: Callable = fetch_logo) -> dict[str, str | None]:
    return {symbol: _sync_one(symbol, root, fetch=fetch)
            for symbol in sorted(set(symbols))}
