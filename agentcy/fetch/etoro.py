"""Hand-rolled eToro public-API client (design 2026-07-10) — READ scope only.

Mirrors agentcy/tg/client.py: urllib.request + json + ssl.create_default_context()
(system CA store; NO certifi in anything we author — NFR7 license requirement).
Unknown JSON fields ignored. 429 honors retryAfter. Read-only: this client has NO
order/trade/close methods by construction — the "advises and monitors, never
executes trades" charter is enforced *structurally*, not just by convention.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
import uuid
from typing import Any

_DEFAULT_HOST = "https://api.etoro.com"  # base host; exact endpoint paths TBD vs api-portal docs


class EtoroError(Exception):
    """Non-retryable eToro API error."""


class EtoroRetryAfter(EtoroError):
    """429: honor retry_after and re-enqueue, never hammer."""

    def __init__(self, retry_after: float):
        super().__init__(f"429 Too Many Requests; retry_after={retry_after}")
        self.retry_after = retry_after


class EtoroClient:
    def __init__(self, *, api_key: str, user_key: str, timeout: float = 20.0,
                 base_url: str = _DEFAULT_HOST) -> None:
        self._api_key = api_key
        self._user_key = user_key
        self._timeout = timeout
        self._base = base_url.rstrip("/")
        self._ctx = ssl.create_default_context()

    # -- transport -----------------------------------------------------------
    def _get(self, path: str) -> Any:
        """GET one path with the three auth headers; a fresh uuid4 per request."""
        req = urllib.request.Request(
            f"{self._base}/{path.lstrip('/')}", method="GET",
            headers={
                "x-request-id": str(uuid.uuid4()),
                "x-api-key": self._api_key,
                "x-user-key": self._user_key,
                "Accept": "application/json",
            })
        try:
            with urllib.request.urlopen(req, timeout=self._timeout, context=self._ctx) as r:
                return _loads(r.read())
        except urllib.error.HTTPError as e:
            data = _loads(e.read())
            if e.code == 429:
                try:
                    ra = float(data.get("retryAfter", 1))
                except (TypeError, ValueError):
                    ra = 1.0
                raise EtoroRetryAfter(ra) from e
            raise EtoroError(f"HTTP {e.code}: {data.get('message', e.reason)}") from e
        except (urllib.error.URLError, TimeoutError) as e:  # DNS, refused, socket timeout
            reason = getattr(e, "reason", e)
            raise EtoroError(f"transport error: {reason}") from e

    # -- READ methods only ---------------------------------------------------
    # Endpoint path strings are placeholders; exact eToro paths get reconciled
    # against api-portal.etoro.com at wiring time. No mutating method exists here.
    def get_positions(self) -> list[dict]:
        return list(self._get("api/v1/user/positions") or [])

    def get_portfolio(self) -> dict:
        return self._get("api/v1/user/portfolio") or {}

    def get_balances(self) -> dict:
        return self._get("api/v1/user/balances") or {}


# -- pure transforms (Task 4) ------------------------------------------------
# No I/O, no network: instrument-type mapping onto the schema taxonomy and
# per-symbol lot aggregation (canonical `position` PK is (snapshot_id, symbol),
# so a symbol's multiple open lots must collapse to ONE row).

_TYPE_MAP = {
    "stocks": "stock", "stock": "stock",
    "etf": "etf", "etfs": "etf",
    "crypto": "crypto", "cryptocurrencies": "crypto", "cryptocurrency": "crypto",
    "copyportfolio": "copyportfolio", "copyportfolios": "copyportfolio",
}


def map_instrument_type(raw: str) -> str:
    """Map an eToro instrument-type label onto the schema taxonomy.

    Case-insensitive and trimmed. Unknown labels raise EtoroError rather than
    silently mis-mapping — mapping to the wrong taxonomy is a correctness bug.
    """
    key = (raw or "").strip().lower()
    if key not in _TYPE_MAP:
        raise EtoroError(f"unknown eToro instrument type: {raw!r}")
    return _TYPE_MAP[key]


def aggregate_lots(symbol: str, lots: list[dict]) -> dict:
    """Collapse a symbol's open lots into one aggregate position row.

    quantity/invested/mv/pnl sum; opened_at = earliest lot; leverage = max
    (so any leveraged lot trips the tripwire); avg_open_price is cost basis
    per unit (None when quantity is zero).
    """
    units = sum(lot["units"] for lot in lots)
    invested = sum(lot["invested"] for lot in lots)
    return {
        "symbol": symbol,
        "quantity": units,
        "invested_native": invested,
        "avg_open_price": (invested / units) if units else None,
        "opened_at": min(lot["open_date"] for lot in lots),  # ISO-8601 dates: lexicographic min == chronological earliest
        "mv_native": sum(lot["mv_native"] for lot in lots),
        "pnl_native": sum(lot["pnl_native"] for lot in lots),
        "leverage": max(lot.get("leverage", 1.0) for lot in lots),
        "lot_count": len(lots),
    }


def _loads(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}
