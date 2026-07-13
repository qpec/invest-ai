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

_DEFAULT_HOST = "https://public-api.etoro.com"  # eToro public API host (verified live)

# Cloudflare in front of the public API returns HTTP 403 "Error 1010
# browser_signature_banned" for the default urllib User-Agent. A browser UA is
# REQUIRED on every request — this is a confirmed, real blocker, not cosmetic.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


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
        """GET one path with all four required headers; a fresh uuid4 per request.

        Headers (verified against the live eToro public API):
          - x-api-key    : the short "Public API Key" (env AGENTCY_ETORO_API_KEY)
          - x-user-key   : the base64 JSON "User Key"  (env AGENTCY_ETORO_USER_KEY)
          - x-request-id : a fresh uuid4 per request
          - user-agent   : a browser UA — REQUIRED, or Cloudflare 403s (Error 1010)
        """
        req = urllib.request.Request(
            f"{self._base}/{path.lstrip('/')}", method="GET",
            headers={
                "x-request-id": str(uuid.uuid4()),
                "x-api-key": self._api_key,
                "x-user-key": self._user_key,
                "user-agent": _BROWSER_UA,
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
    # Only the two real eToro public-API GET endpoints. No mutating method
    # exists here by construction (the "never executes trades" charter).
    def get_portfolio(self) -> dict:
        """GET /api/v1/trading/info/portfolio -> the raw JSON body.

        The body wraps the holdings under "clientPortfolio": {positions, credit, ...}.
        """
        return self._get("api/v1/trading/info/portfolio") or {}

    def get_instruments(self, instrument_ids) -> list[dict]:
        """GET /api/v1/market-data/instruments?instrumentIDs=id1,id2,... -> the
        list under "instrumentDisplayDatas" (instrumentID -> symbolFull + type).

        `instrument_ids` is an iterable of ints/strings; an empty set short-circuits
        (no network) to []."""
        ids = [str(i) for i in instrument_ids]
        if not ids:
            return []
        joined = ",".join(ids)
        body = self._get(f"api/v1/market-data/instruments?instrumentIDs={joined}")
        if isinstance(body, dict):
            return list(body.get("instrumentDisplayDatas") or [])
        return []


# -- pure transforms ---------------------------------------------------------
# No I/O, no network: instrument-type mapping onto the schema taxonomy and
# per-instrument lot aggregation (canonical `position` PK is (snapshot_id, symbol),
# so an instrument's multiple open lots must collapse to ONE row).

# eToro's real portfolio has no per-position native currency field; amounts are
# settled/quoted in USD ("initialAmountInDollars"). USD is the native currency and
# the FX seam crosses it to EUR downstream.
_NATIVE_CCY = "USD"

# instrumentTypeID -> schema taxonomy. 5 = stock, 6 = ETF are the confirmed live
# values; anything else is best-effort-defaulted (the existing 'stock' default).
_TYPE_ID_MAP = {5: "stock", 6: "etf"}
_DEFAULT_TYPE = "stock"


def map_instrument_type(type_id) -> str:
    """Map an eToro numeric ``instrumentTypeID`` onto the schema taxonomy.

    5 -> 'stock', 6 -> 'etf'. Any other (or missing) id maps best-effort to the
    existing default ('stock') rather than raising — the taxonomy only gates
    balance/outside-framework accounting, and an unknown eToro instrument type
    must not crash the whole pull.
    """
    try:
        key = int(type_id)
    except (TypeError, ValueError):
        return _DEFAULT_TYPE
    return _TYPE_ID_MAP.get(key, _DEFAULT_TYPE)


def aggregate_lots(symbol: str, lots: list[dict]) -> dict:
    """Collapse an instrument's open lots (real eToro position objects) into one
    aggregate position row.

    Real position objects carry only ENTRY data — there is NO current-market-value
    or unrealized-PnL field — so we map what is present:
      quantity      = sum(units)
      invested/mv   = sum(amount)   (invested-native; current MV comes from yfinance)
      opened_at     = min(openDateTime)   (the invested moment; earliest lot)
      avg_open_price= sum(amount)/sum(units)   (None when quantity is zero)
      leverage      = max(leverage)   (any leveraged lot trips the Hell-No tripwire)
      direction     = 'buy' if the first lot isBuy else 'sell'
    """
    units = sum(lot["units"] for lot in lots)
    invested = sum(lot["amount"] for lot in lots)
    return {
        "symbol": symbol,
        "quantity": units,
        "invested_native": invested,
        "avg_open_price": (invested / units) if units else None,
        # openDateTime is ISO-8601 with a trailing Z: lexicographic min == earliest.
        "opened_at": min(lot["openDateTime"] for lot in lots),
        "mv_native": invested,          # no live MV in the payload; invested is the native value
        "leverage": max(lot.get("leverage", 1.0) for lot in lots),
        "lot_count": len(lots),
        "direction": "buy" if lots[0].get("isBuy", True) else "sell",
    }


# -- snapshot adapter --------------------------------------------------------
# Turns the client's raw portfolio into the canonical SnapshotIn, capturing rich
# per-position detail. FX is an INJECTABLE seam (callable) so tests are deterministic
# and no network is needed. mirror does not import etoro, so this import is not circular.


def fetch_etoro_snapshot(
    client, *, fx: Callable[[float, str], float], as_of: str
) -> "mirror.SnapshotIn":
    """Adapt the eToro public-API portfolio into a canonical SnapshotIn + details.

    Contract:
      - client.get_portfolio() -> {"clientPortfolio": {"positions": [...], "credit": N}}
      - client.get_instruments(ids) -> [{"instrumentID", "symbolFull", "instrumentTypeID"}]

    `fx(amount, currency) -> eur` converts native (USD) amounts to EUR (injectable seam).
    `as_of` is an ISO date string. Lots are grouped by ``instrumentID``, each id is
    resolved to its ``symbolFull`` ticker + type, multiple lots per instrument collapse
    to one PositionIn + one PositionDetailIn, and cash comes from ``clientPortfolio.credit``.
    """
    portfolio = client.get_portfolio()
    if not isinstance(portfolio, dict):
        raise EtoroError(
            f"expected a portfolio object, got {type(portfolio).__name__}")
    client_portfolio = portfolio.get("clientPortfolio")
    if not isinstance(client_portfolio, dict):
        raise EtoroError(
            "eToro portfolio body missing 'clientPortfolio' object")
    raw_positions = client_portfolio.get("positions", [])
    # SHAPE GUARD: reject anything that is not a list of dicts so a bad payload
    # can't silently corrupt the snapshot.
    if not isinstance(raw_positions, list):
        raise EtoroError(
            f"expected a list of positions, got {type(raw_positions).__name__}")
    for element in raw_positions:
        if not isinstance(element, dict):
            raise EtoroError(
                f"expected each position to be a dict, got {type(element).__name__}")

    # Group lots by instrumentID (order-preserving on first sight).
    groups: dict[int, list[dict]] = {}
    for pos in raw_positions:
        iid = pos.get("instrumentID")
        if iid is None:
            raise EtoroError(f"position missing instrumentID: {pos!r}")
        groups.setdefault(iid, []).append(pos)

    # One metadata call for the distinct instrumentIDs -> symbolFull + type.
    meta = _resolve_instruments(client, list(groups.keys()))

    position_ins: list[mirror.PositionIn] = []
    detail_ins: list[mirror.PositionDetailIn] = []
    for iid, lots in groups.items():
        info = meta.get(iid)
        if info is None:
            raise EtoroError(f"instrument metadata unavailable for instrumentID {iid}")
        symbol = info["symbol"]
        itype = info["instrument_type"]
        agg = aggregate_lots(symbol, lots)
        mv_native = agg["mv_native"]
        mv_eur = fx(mv_native, _NATIVE_CCY)
        invested_native = agg["invested_native"]
        invested_eur = fx(invested_native, _NATIVE_CCY)
        first = lots[0]
        position_ins.append(mirror.PositionIn(
            symbol=symbol, yf_ticker=mirror._yf_for(symbol, itype), instrument_type=itype,
            quantity=agg["quantity"], avg_open_price=agg["avg_open_price"],
            native_currency=_NATIVE_CCY, mv_native=mv_native, mv_eur=mv_eur,
            weight=0.0, leverage=agg["leverage"]))  # weight filled after totals
        detail_ins.append(mirror.PositionDetailIn(
            symbol=symbol, opened_at=agg["opened_at"], invested_native=invested_native,
            invested_eur=invested_eur,
            # no unrealized-PnL data in the portfolio payload (entry-only)
            unrealized_pnl_native=None, unrealized_pnl_pct=None,
            current_rate=first.get("openRate"), direction=agg["direction"],
            lot_count=agg["lot_count"], raw_json=json.dumps(lots, default=str)))

    # weight = fraction of invested MV (mirror the CSV/manual adapters); ingest recomputes
    # this authoritatively, so consistency matters more than being the source of truth.
    total = sum(p.mv_eur for p in position_ins) or 1.0
    position_ins = [
        dataclasses.replace(p, weight=p.mv_eur / total) for p in position_ins]

    # Available cash balance is clientPortfolio.credit (native ~USD).
    cash_native = client_portfolio.get("credit", 0.0) or 0.0
    cash_balance_eur = fx(cash_native, _NATIVE_CCY)

    return mirror.SnapshotIn(
        as_of=as_of, source="api_pull", cash_balance_eur=cash_balance_eur,
        positions=tuple(position_ins), details=tuple(detail_ins))


def _resolve_instruments(client, instrument_ids: list) -> dict:
    """One get_instruments call -> {instrumentID: {'symbol', 'instrument_type'}}.

    Fails loud (EtoroError) if a resolved row is missing its symbolFull — a
    position we cannot name must not silently vanish from the snapshot."""
    out: dict = {}
    for row in client.get_instruments(instrument_ids):
        if not isinstance(row, dict):
            continue
        iid = row.get("instrumentID")
        symbol = row.get("symbolFull")
        if iid is None:
            continue
        if not symbol:
            raise EtoroError(f"instrument {iid} has no symbolFull ticker")
        out[iid] = {
            "symbol": symbol,
            "instrument_type": map_instrument_type(row.get("instrumentTypeID")),
        }
    return out


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
