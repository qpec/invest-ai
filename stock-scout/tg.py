"""Stdlib-only Telegram Bot API client (RECONSTRUCTION.md §2; used by reporter.py §5.4
and grade.py --telegram).

send_message / send_document via urllib. Token and chat id come from
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (or explicit arguments); without them the
functions print the payload to stdout and return False — dev mode, NEVER an
exception on missing config. Transport errors are also swallowed to a False return
(the detached reporter must not die on one flaky send).
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.request
import uuid
from pathlib import Path

API_BASE = "https://api.telegram.org"


def _config(token: str | None, chat_id: str | None) -> tuple[str | None, str | None]:
    """Explicit args win; fall back to the TELEGRAM_* environment."""
    return (token or os.environ.get("TELEGRAM_BOT_TOKEN"),
            chat_id or os.environ.get("TELEGRAM_CHAT_ID"))


def _post(url: str, body: bytes, content_type: str) -> bool:
    req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print(f"[tg] send failed: {e}", file=sys.stderr)
        return False


def send_message(text: str, parse_mode: str = "HTML", *, token: str | None = None,
                 chat_id: str | None = None) -> bool:
    """sendMessage; True on a 2xx response. Without config: print the text (dev mode)
    and return False."""
    token, chat = _config(token, chat_id)
    if not token or not chat:
        print(f"[tg dev] sendMessage: {text}")
        return False
    body = json.dumps({"chat_id": chat, "text": text, "parse_mode": parse_mode}).encode("utf-8")
    return _post(f"{API_BASE}/bot{token}/sendMessage", body, "application/json")


def _multipart(fields: dict, file_field: str, path: Path) -> tuple[bytes, str]:
    """Hand-rolled multipart/form-data body (stdlib has no builder)."""
    boundary = "----stock-scout-" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts += [b"--" + boundary.encode(),
                  f'Content-Disposition: form-data; name="{name}"'.encode(),
                  b"", str(value).encode("utf-8")]
    ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    parts += [b"--" + boundary.encode(),
              f'Content-Disposition: form-data; name="{file_field}"; filename="{path.name}"'.encode(),
              f"Content-Type: {ctype}".encode(), b"", path.read_bytes()]
    parts += [b"--" + boundary.encode() + b"--", b""]
    return b"\r\n".join(parts), f"multipart/form-data; boundary={boundary}"


def send_document(path, caption: str | None = None, *, token: str | None = None,
                  chat_id: str | None = None) -> bool:
    """sendDocument (urllib multipart); True on a 2xx response. Without config: print
    the intended payload (dev mode) and return False."""
    token, chat = _config(token, chat_id)
    p = Path(path)
    if not token or not chat:
        print(f"[tg dev] sendDocument: {p}" + (f" caption={caption!r}" if caption else ""))
        return False
    fields = {"chat_id": chat}
    if caption:
        fields["caption"] = caption
    body, content_type = _multipart(fields, "document", p)
    return _post(f"{API_BASE}/bot{token}/sendDocument", body, content_type)
