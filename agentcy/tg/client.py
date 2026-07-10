"""Hand-rolled Telegram Bot API client (tech-arch §5.1) — eight methods + one file GET.

urllib.request + json + ssl.create_default_context() (system CA store; NO certifi in
anything we author). Unknown JSON fields ignored. 429 honors retry_after. Every call
carries a <=35s timeout. Only the daemon calls get_updates; any process may send.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Mapping

_DEFAULT_HOST = "https://api.telegram.org"


class TelegramError(Exception):
    """Non-retryable API error (ok=false, no retry_after)."""


class TelegramRetryAfter(TelegramError):
    """429: honor retry_after and re-enqueue, never hammer."""

    def __init__(self, retry_after: float):
        super().__init__(f"429 Too Many Requests; retry_after={retry_after}")
        self.retry_after = retry_after


class TelegramClient:
    def __init__(self, token: str, *, timeout: float = 10.0, base_url: str = _DEFAULT_HOST) -> None:
        self._token = token
        self._timeout = timeout
        self._base = base_url.rstrip("/")
        self._ctx = ssl.create_default_context()

    # -- transport -----------------------------------------------------------
    def _api_url(self, method: str) -> str:
        return f"{self._base}/bot{self._token}/{method}"

    def _request(self, method: str, payload: Mapping[str, Any], *, timeout: float | None = None) -> Any:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._api_url(method), data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        return self._do(req, timeout=timeout)

    def _do(self, req, *, timeout: float | None) -> Any:
        eff = self._timeout if timeout is None else timeout
        try:
            with urllib.request.urlopen(req, timeout=eff, context=self._ctx) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            data = _loads(raw)
            if e.code == 429 or data.get("error_code") == 429:
                ra = float(data.get("parameters", {}).get("retry_after", 1))
                raise TelegramRetryAfter(ra)
            raise TelegramError(data.get("description", f"HTTP {e.code}"))
        data = _loads(raw)
        if not data.get("ok", False):
            if data.get("error_code") == 429:
                ra = float(data.get("parameters", {}).get("retry_after", 1))
                raise TelegramRetryAfter(ra)
            raise TelegramError(data.get("description", "ok=false"))
        return data.get("result")

    # -- methods -------------------------------------------------------------
    def get_updates(self, *, offset: int, timeout: int = 25, limit: int = 25) -> list[dict]:
        """Long-poll (read timeout 35s); only the daemon ever calls this."""
        result = self._request(
            "getUpdates", {"offset": offset, "timeout": timeout, "limit": limit},
            timeout=timeout + 10)  # 25 + 10 = 35s read window (§5.2)
        return list(result or [])

    def send_message(self, chat_id: int, html: str, *, reply_markup: dict | None = None) -> dict:
        """parse_mode=HTML, locked; returns the message object."""
        payload: dict[str, Any] = {"chat_id": chat_id, "text": html, "parse_mode": "HTML"}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._request("sendMessage", payload)


def _loads(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}
