"""Hand-rolled eToro public-API client (design 2026-07-10) — READ scope only.

Mirrors agentcy/tg/client.py: urllib.request + json + ssl.create_default_context()
(system CA store; NO certifi in anything we author — NFR7 license requirement).
Unknown JSON fields ignored. 429 honors retryAfter. Read-only: this client has NO
order/trade/close methods by construction — the "advises and monitors, never
executes trades" charter is enforced *structurally*, not just by convention.
"""
from __future__ import annotations

import dataclasses
import json
import ssl
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable

from agentcy import mirror  # mirror does not import etoro -> no circular import

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


# -- snapshot adapter (Task 5) ----------------------------------------------
# Turns the client's raw positions/balances into the canonical SnapshotIn, capturing
# rich per-position detail. FX is an INJECTABLE seam (callable) so tests are deterministic
# and no network is needed. mirror does not import etoro, so this import is not circular.
# eToro lot dict -> the keys aggregate_lots expects. The eToro field names are
# placeholders reconciled at wiring time; we normalize from the input keys here.
_LOT_KEYS = ("units", "invested", "open_rate", "open_date", "mv_native", "pnl_native", "leverage")


def _is_cash(pos: dict) -> bool:
    """A cash entry is not an instrument — it is folded/skipped (cash comes from balances)."""
    if str(pos.get("symbol", "")).strip().upper() == "CASH":
        return True
    return str(pos.get("type", "")).strip().lower() == "cash"


def _normalize_lot(pos: dict) -> dict:
    """Project a raw eToro position dict onto the keys aggregate_lots consumes."""
    lot = {k: pos[k] for k in _LOT_KEYS if k in pos}
    lot.setdefault("leverage", 1.0)
    return lot


def fetch_etoro_snapshot(
    client, *, fx: Callable[[float, str], float], as_of: str
) -> "mirror.SnapshotIn":
    """Adapt the eToro client's data into a canonical SnapshotIn + per-position details.

    `fx(amount, currency) -> eur` converts native amounts to EUR (injectable seam).
    `as_of` is an ISO date string. Cash entries in positions are folded/skipped; cash
    comes from get_balances(). Multiple lots per symbol collapse to one PositionIn +
    one PositionDetailIn (canonical position PK is (snapshot_id, symbol)).
    """
    raw_positions = client.get_positions()
    # SHAPE GUARD: a malformed API body may be coerced to dict-keys; reject anything
    # that is not a list of dicts so a bad payload can't silently corrupt the snapshot.
    if not isinstance(raw_positions, list):
        raise EtoroError(
            f"expected a list of positions, got {type(raw_positions).__name__}")
    for element in raw_positions:
        if not isinstance(element, dict):
            raise EtoroError(
                f"expected each position to be a dict, got {type(element).__name__}")

    # Partition out cash; group the rest by symbol (order-preserving on first sight).
    groups: dict[str, list[dict]] = {}
    for pos in raw_positions:
        if _is_cash(pos):
            continue
        groups.setdefault(pos["symbol"], []).append(pos)

    position_ins: list[mirror.PositionIn] = []
    detail_ins: list[mirror.PositionDetailIn] = []
    for symbol, lots in groups.items():
        agg = aggregate_lots(symbol, [_normalize_lot(p) for p in lots])
        itype = map_instrument_type(lots[0].get("type", ""))
        native_ccy = lots[0].get("currency", "EUR")
        mv_eur = fx(agg["mv_native"], native_ccy)
        invested_native = agg["invested_native"]
        invested_eur = fx(invested_native, native_ccy)
        first = lots[0]
        position_ins.append(mirror.PositionIn(
            symbol=symbol, yf_ticker=mirror._yf_for(symbol, itype), instrument_type=itype,
            quantity=agg["quantity"], avg_open_price=agg["avg_open_price"],
            native_currency=native_ccy, mv_native=agg["mv_native"], mv_eur=mv_eur,
            weight=0.0, leverage=agg["leverage"]))  # weight filled after totals
        detail_ins.append(mirror.PositionDetailIn(
            symbol=symbol, opened_at=agg["opened_at"], invested_native=invested_native,
            invested_eur=invested_eur, unrealized_pnl_native=agg["pnl_native"],
            unrealized_pnl_pct=(agg["pnl_native"] / invested_native * 100)
            if invested_native else None,
            current_rate=first.get("current_rate"), direction=first.get("direction"),
            lot_count=agg["lot_count"], raw_json=json.dumps(lots)))

    # weight = fraction of invested MV (mirror the CSV/manual adapters); ingest recomputes
    # this authoritatively, so consistency matters more than being the source of truth.
    total = sum(p.mv_eur for p in position_ins) or 1.0
    position_ins = [
        dataclasses.replace(p, weight=p.mv_eur / total) for p in position_ins]

    balances = client.get_balances()
    cash_native = balances.get("cash", 0.0)
    cash_ccy = balances.get("currency", "EUR")
    cash_balance_eur = fx(cash_native, cash_ccy)

    return mirror.SnapshotIn(
        as_of=as_of, source="api_pull", cash_balance_eur=cash_balance_eur,
        positions=tuple(position_ins), details=tuple(detail_ins))


def _loads(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}
