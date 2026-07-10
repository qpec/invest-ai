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
from agentcy.fetch import store

_DEFAULT_HOST = "https://api.etoro.com"  # base host; exact endpoint paths TBD vs api-portal docs


class EtoroError(Exception):
    """Non-retryable eToro API error."""


class EtoroRetryAfter(EtoroError):
    """429: honor retry_after and re-enqueue, never hammer."""

    def __init__(self, retry_after: float):
        super().__init__(f"429 Too Many Requests; retry_after={retry_after}")
        self.retry_after = retry_after


def build_client(api_key, user_key) -> "EtoroClient":
    """Shared constructor for the eToro Read-API client (the one factory the weekly-auto
    and CLI `_etoro_client` seams delegate to, so the two do not drift). Those module-level
    `_etoro_client` functions stay as the tests' monkeypatch points."""
    return EtoroClient(api_key=api_key, user_key=user_key)


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
        # The shape guard only guarantees dicts, not a `symbol` key; raise a typed
        # error (not a bare KeyError) consistent with the rest of the shape-guarding.
        if not pos.get("symbol"):
            raise EtoroError(f"position missing symbol: {pos!r}")
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
        # group-level fields (currency, type, direction, current_rate) taken from the
        # first lot — all lots of a symbol are assumed to share these; revisit if
        # hedged/mixed-direction positions appear.
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
            lot_count=agg["lot_count"], raw_json=json.dumps(lots, default=str)))

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


# -- default FX factory (Task 7) --------------------------------------------
# fetch_etoro_snapshot (Task 5) takes an injected `fx(amount, currency) -> eur`.
# In production we back that seam with the project's ONE canonical FX helper,
# store.fx_rate_eur — the same {CUR}EUR=X, DB-price-cache-backed path the daily
# and quarterly jobs use — instead of reinventing a second FX convention. It
# stays INJECTABLE: this factory returns an `fx` closure, and the rate source
# (`rate_source`) is itself a seam so tests inject a fake and no network/DB is hit.


def default_fx(conn, *, as_of, rate_source=None) -> Callable[[float, str], float]:
    """Build the production `fx(amount, currency) -> eur` closure for Task 5's seam,
    backed by the project's canonical ``store.fx_rate_eur`` ({CUR}EUR=X, DB-cached).

    Conversion convention (documented precisely):
      - ``store.fx_rate_eur(conn, cur, as_of=...)`` quotes the pair ``{cur}EUR=X``
        and returns a ``Stamped`` whose ``.value`` is EUR per **1 unit of cur**
        (e.g. USDEUR=X ~= 0.92 means 1 USD is worth 0.92 EUR). To convert a native
        amount to EUR we therefore MULTIPLY by that rate::

            eur = amount * rate            # rate = EUR per 1 unit of currency

        Worked example: 100 USD at USDEUR=X = 0.92  ->  100 * 0.92 = 92.00 EUR.

    EUR is the identity currency (case-insensitive). ``store.fx_rate_eur`` already
    returns rate 1.0 FRESH for EUR, but we short-circuit it here to avoid a needless
    call — ``fx(amount, "EUR")`` returns ``amount`` unchanged.

    Memoization: the resolved float rate for each currency is cached in the closure,
    so converting N USD positions costs ONE lookup, not N.

    `rate_source(conn, currency, *, as_of) -> Stamped | None` is the injectable seam.
    When None, the real ``store.fx_rate_eur`` is used. Tests inject a fake so no
    network/DB is touched.

    Fail-loud: if the source returns ``None`` (the {cur}EUR=X pair is not cached) or
    a non-positive / None rate, raise ``EtoroError`` — Task 9's weekly fallback
    catches ``EtoroError``.
    """
    lookup = rate_source if rate_source is not None else store.fx_rate_eur
    cache: dict[str, float] = {}

    def fx(amount: float, currency: str) -> float:
        cur = (currency or "").strip().upper()
        if cur == "EUR":
            return amount
        rate = cache.get(cur)
        if rate is None:
            stamped = lookup(conn, cur, as_of=as_of)
            if stamped is None:
                raise EtoroError(
                    f"FX rate unavailable for {cur} ({cur}EUR=X not cached)")
            rate = stamped.value
            if rate is None or rate <= 0:
                raise EtoroError(
                    f"FX rate unavailable for {cur} ({cur}EUR=X not cached): "
                    f"non-positive or missing rate {rate!r}")
            cache[cur] = rate
        return amount * rate

    return fx


# -- self-priming production FX (Task 8, Piece A) ----------------------------
# default_fx fails loud on a cache miss; for a FIRST eToro pull nothing is cached
# yet. production_fx composes default_fx with a rate_source that fetches {CUR}EUR=X
# on a miss and stores it (same yfinance path daily.refresh_prices uses), so a
# first pull / a newly-seen currency self-heals. `bar_fetcher` and `bar_store` are
# the INJECTABLE seams so tests never hit the network or the price DB.


def production_fx(conn, *, as_of, state_dir, clock, run_id=None,
                  bar_fetcher=None, bar_store=None):
    """The fx(amount, currency)->EUR used by the CLI and weekly-auto. Backed by
    store.fx_rate_eur, but on a cache miss it fetches {CUR}EUR=X via yfinance
    (paced) and stores it, so a first pull / new currency self-heals. Fail-loud
    (EtoroError) if the fetch fails or the rate is still unavailable."""
    from agentcy import db
    from agentcy.fetch import yf

    fetch = bar_fetcher if bar_fetcher is not None else yf.fetch_daily_bars
    put = bar_store if bar_store is not None else store.store_price_bars

    def rate_source(conn2, cur, *, as_of):
        stamped = store.fx_rate_eur(conn2, cur, as_of=as_of)
        if stamped is not None:
            return stamped
        # Cache miss: prime {CUR}EUR=X the same way daily.refresh_prices does.
        pair = f"{cur}EUR=X"
        try:
            frame = fetch(pair, state_dir=state_dir)
            put(conn2, pair, frame, run_id=run_id, fetched_at=db.to_iso(clock.now()))
        except yf.FetchFailed as e:
            raise EtoroError(f"FX fetch failed for {pair}: {e}") from e
        # Re-read after priming (may still be None -> default_fx raises EtoroError).
        return store.fx_rate_eur(conn2, cur, as_of=as_of)

    return default_fx(conn, as_of=as_of, rate_source=rate_source)


def _loads(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}
