"""Paced, resumable yfinance fundamentals cache builder (RECONSTRUCTION.md §3.2, §5.2).

Per symbol (default one pass, msg 62 "nu mét kwartaaldata in één pass"; --annual-only
reproduces the v1 path): fast_info, daily bars (5y, so the same single history call
also yields the split events), shares_full, annual + quarterly statements ->
cache/<SYM>.json exactly per §3.2 (NaN -> null, ISO period ends, full row payloads,
shares deduped last-per-date, splits as {date: ratio}). Fresh entries are skipped
(--max-age-days 3); failures are never fatal — one failures.log line + the failed
count in progress.json (msg 6: 404s on dead tickers are logged and skipped);
progress.json is rewritten after EVERY symbol so the detached reporter (§5.4) always
reads a truthful state. --fresh sets the old cache aside as cache-<date> (msg 62).
Pacing lives in vendor/yf_fetch (flock + spacing + rate-limit ladder); the lock
state_dir is the cache dir's parent, so every process on the box serializes on the
same lock.

Price source (§5.2 --price-source {auto,yahoo,stockanalysis}): Yahoo's daily bars stay
the default leg — they carry the currency and the §3.2 split events on the same call —
and any other vendor is served by pricesrc, which DECLARES the share terms of its closes.
That declaration is written into every entry as `price_basis` (§3.2); a reader never has
to know who produced a file to know what its close means. For THIS module the two bases
coincide: "split-adjusted to today" IS the as-traded price today, so a live market cap
built on a stockanalysis close is exact — a full substitute, not a compromise. Only a
HISTORICAL close differs by the split factor, which is the backtest's problem (§3.6,
§6.17). What the fallback has no feed for is splits, so its entries carry none and
deviation 8's restatement stays inert for them — the run reports that.

Pure parts (build_cache_entry, statement_payload, shares_payload, splits_payload,
write_progress, is_fresh) do no I/O beyond their arguments and are unit-tested offline.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import pit
from vendor import yf_fetch

PROGRESS_FILE = "progress.json"
FAILURES_FILE = "failures.log"
STATEMENT_TYPES = ("income", "balance", "cashflow")
# The bar fetch doubles as the split-history fetch (§3.2 "splits"): one history call,
# widened to cover the cached share series, instead of a second Yahoo request.
PRICE_PERIOD = "5y"

YAHOO_SOURCE, AUTO_SOURCE = "yahoo", "auto"
FALLBACK_SOURCE = "stockanalysis"   # the keyless pricesrc source `auto` steps down to
PRICE_SOURCES = (AUTO_SOURCE, YAHOO_SOURCE, FALLBACK_SOURCE)   # == pricesrc.available()


# ---------------------------------------------------------------- pure builders

def _num(v):
    """Statement cell -> float | None (NaN/inf -> null per §3.2) | str for the rare
    non-numeric Yahoo cell."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f if math.isfinite(f) else None


def _scalar(v):
    """fast_info value -> plain JSON scalar (§3.2 'plain floats/strings')."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, datetime):
        return v.isoformat()
    item = getattr(v, "item", None)  # numpy scalars
    if callable(item):
        try:
            return _scalar(v.item())
        except (TypeError, ValueError):
            pass
    return str(v)


def _meta(v):
    """Universe cell -> str | None (a NaN sector/industry must not become 'nan')."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return str(v)


def statement_payload(frame: pd.DataFrame) -> dict:
    """One Yahoo statement frame -> {ISO period_end: {row: float|null}} keeping
    EVERY row Yahoo returns (§3.2 — the datasheet shows the exact matched labels)."""
    out = {}
    for col in frame.columns:
        payload = {}
        for row_label, value in frame[col].items():
            payload[str(row_label)] = _num(value)
        out[pd.Timestamp(col).date().isoformat()] = payload
    return dict(sorted(out.items()))


def splits_payload(bars: pd.DataFrame) -> dict:
    """Split events out of the daily-bar frame -> {ISO date: ratio} (§3.2 "splits").
    Yahoo writes 0.0 on every ordinary day and the ratio (2.0, 0.1, ...) on the effective
    date; only real events are kept. A frame without the column (older callers, synthetic
    fixtures) yields {} — absent splits mean no adjustment, never a guess."""
    out = {}
    if bars is None or "split" not in getattr(bars, "columns", []):
        return out
    for ts, v in bars["split"].items():
        f = _num(v)
        if isinstance(f, float) and f > 0.0 and f != 1.0:
            out[pd.Timestamp(ts).date().isoformat()] = f
    return dict(sorted(out.items()))


def shares_payload(series: pd.Series) -> dict:
    """get_shares_full series -> {ISO date: float}, deduped last-per-date (§3.2):
    chronological iteration + dict overwrite keeps the last observation per date."""
    out = {}
    for ts, v in series.items():
        f = _num(v)
        if not isinstance(f, float):
            continue
        out[pd.Timestamp(ts).date().isoformat()] = f
    return dict(sorted(out.items()))


def build_cache_entry(symbol: str, meta: dict, fast_info: dict, bars: pd.DataFrame,
                      shares: pd.Series | None, annual: dict, quarterly: dict | None = None,
                      *, fetched_at: datetime | None = None, splits: dict | None = None,
                      price_basis: str = pit.BASIS_RAW) -> dict:
    """Assemble one cache/<SYM>.json payload per §3.2 — pure and JSON-serializable
    with allow_nan=False. `quarterly` None -> the key is absent (pre-augment shape).
    `splits` defaults to the split events carried by the bar frame (§3.2 "splits"): the
    scoring layer needs them to restate the raw share series in today's share terms, so a
    split does not read as dilution (§4.3). `price_basis` DECLARES the share terms of the
    close (§3.2/§3.6) — Yahoo's bars are as-traded, hence the default; it is always written
    out, even when it is that default, so no reader has to infer it from the vendor."""
    fetched_at = fetched_at or datetime.now(timezone.utc)
    currency = None
    if "currency" in bars.columns and len(bars):
        currency = str(bars["currency"].iloc[-1]) or None
    if not currency:
        currency = _meta(fast_info.get("currency")) if fast_info else None
    entry = {
        "ticker": symbol,
        "fetched_at": fetched_at.isoformat(),
        "meta": {k: _meta(meta.get(k)) for k in ("name", "sector", "industry", "country")},
        "currency": currency,
        "price": {"close": float(bars["close"].iloc[-1]),
                  "date": pd.Timestamp(bars.index[-1]).date().isoformat()},
        "price_basis": pit.checked_basis(price_basis),
        "fast_info": {str(k): _scalar(v) for k, v in (fast_info or {}).items()},
        "shares": shares_payload(shares) if shares is not None and len(shares) else {},
        "splits": dict(splits) if splits is not None else splits_payload(bars),
        "annual": {st: statement_payload(annual[st]) for st in STATEMENT_TYPES},
    }
    if quarterly is not None:
        entry["quarterly"] = {st: statement_payload(quarterly[st]) for st in STATEMENT_TYPES}
    return entry


def cache_filename(symbol: str) -> str:
    """§3.2: dots in symbols are kept, '/' -> '-'."""
    return symbol.replace("/", "-") + ".json"


# ------------------------------------------------------------ shared file contracts

def atomic_write_json(path, obj) -> None:
    """tmp + os.replace; allow_nan=False enforces the §3.2 NaN->null contract."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def write_progress(path, *, task: str, total: int, done: int, failed: int,
                   started_at: str, finished: bool = False,
                   finished_at: str | None = None) -> dict:
    """The §3.2 progress.json payload, written atomically after EVERY symbol so the
    detached reporter never reads junk."""
    payload = {"task": task, "total": total, "done": done, "failed": failed,
               "started_at": started_at, "finished": finished, "finished_at": finished_at}
    atomic_write_json(path, payload)
    return payload


def append_failure(path, symbol: str, reason) -> None:
    """One 'symbol<TAB>reason' line per failure (§3.2); newlines flattened."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{symbol}\t{' '.join(str(reason).split())}\n")


def is_fresh(path, *, max_age_days: float, need_quarterly: bool,
             now: datetime | None = None) -> bool:
    """Resumability check (§5.2): the entry exists, parses, its fetched_at is younger
    than max_age_days, and it already carries quarterly when this run needs it."""
    try:
        entry = json.loads(Path(path).read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(entry["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now - fetched > timedelta(days=max_age_days):
        return False
    if need_quarterly and "quarterly" not in entry:
        return False
    return "annual" in entry


# -------------------------------------------------- shared price-source selection

def price_sources():
    """The pricesrc module, imported HERE and not at module scope (§5.2/§5.8): the
    fundamentals half of this pipeline must keep importing and running on a box where the
    price layer is unavailable, which mirrors pricesrc's own lazy vendor import."""
    import pricesrc
    return pricesrc


class PriceLadder:
    """Which price vendor a run uses — shared by populate (§5.2) and bt_fetch (§5.8).

    Both modules keep their OWN Yahoo fetch (populate's daily bars carry the currency and
    the §3.2 split events; bt_fetch's weekly path carries the raw close), so this holds
    only the choice around it: is the Yahoo leg still in play, which pricesrc source stands
    behind it, and which exceptions mean "throttled" for the layers involved.

    `auto` runs Yahoo first and steps down to the fallback; a rate limit RETIRES the Yahoo
    leg for the rest of the run, because every remaining symbol would otherwise pay the
    same 30 s -> 5 min -> 30 min ladder — that is the entire point on a 429'd box. An
    explicit `--price-source yahoo` has no fallback, so its rate limit still stops the run
    exactly as before, and a named non-Yahoo source skips the Yahoo leg altogether."""

    def __init__(self, name: str = AUTO_SOURCE):
        name = str(name).strip().lower()
        if name not in PRICE_SOURCES:
            raise ValueError(f"unknown price source {name!r} — "
                             f"available: {list(PRICE_SOURCES)}")
        self.name = name
        self.yahoo = name in (AUTO_SOURCE, YAHOO_SOURCE)
        self.fallback = None
        rate_limited = [yf_fetch.RateLimited]
        if name != YAHOO_SOURCE:
            pricesrc = price_sources()
            self.fallback = pricesrc.get(FALLBACK_SOURCE if name == AUTO_SOURCE else name)
            rate_limited.append(pricesrc.RateLimited)
        self.rate_limited = tuple(rate_limited)

    def yahoo_leg_failed(self, exc: Exception) -> None:
        """What to do when the caller's own Yahoo fetch raised. Without a fallback the
        exception is re-raised, i.e. the pre-existing behavior (a rate limit stops the
        run). With one, a RATE LIMIT retires the Yahoo leg for the remaining symbols and a
        plain fetch failure retires nothing — that one is usually about the one symbol."""
        if self.fallback is None:
            raise exc
        if isinstance(exc, yf_fetch.RateLimited):
            self.yahoo = False
            print(f"yahoo rate-limited — de rest van de run haalt koersen bij "
                  f"{self.fallback.name} ({self.fallback.basis})", file=sys.stderr)


# ------------------------------------------------------------------- fetch pass

def latest_frame(bars: dict) -> pd.DataFrame:
    """A §3.6 bar map -> the one-row frame build_cache_entry reads its §3.2 price block
    off: the newest bar's close on that bar's own date. A weekly bar is dated by its week,
    so the date is the week's, not the trading day's — the close is still the last one the
    vendor has. No currency column is invented for a vendor that states none; the entry
    then takes fast_info's currency (§3.2)."""
    day = max(bars)
    close = pit.bar_value(bars[day], pit.DEFAULT_PRICE_FIELD)
    return pd.DataFrame({"close": [float(close)]}, index=pd.DatetimeIndex([day]))


def price_bars(symbol: str, ladder: PriceLadder, *, state_dir: Path
               ) -> tuple[pd.DataFrame, dict | None, str]:
    """(bar frame, split events or None, declared basis) for one symbol's §3.2 price block.

    The Yahoo leg is the unchanged 5y daily fetch: it carries the currency and its splits
    ride the same call, so it hands back None (build_cache_entry then reads them off the
    frame). A pricesrc source hands back its newest weekly bar plus whatever split feed it
    has — {} for the keyless ones, i.e. no events KNOWN, never a fake ratio — and its own
    declared basis, which for a live close is the as-traded price of today either way."""
    if ladder.yahoo:
        try:
            bars = yf_fetch.fetch_daily_bars(symbol, state_dir=state_dir,
                                             period=PRICE_PERIOD)
        except Exception as e:
            ladder.yahoo_leg_failed(e)     # re-raises unless a fallback can take over
        else:
            return bars, None, pit.BASIS_RAW
    source = ladder.fallback
    return (latest_frame(source.weekly(symbol, state_dir=state_dir)),
            source.splits(symbol), source.basis)


def fetch_entry(symbol: str, meta: dict, state_dir: Path, *, annual_only: bool,
                ladder: PriceLadder) -> dict:
    """One symbol's full paced fetch (§5.2). fast_info, price bars and annual
    statements are required; shares and quarterly degrade on FetchFailed (shares ->
    {} keeps the M leg computable-from-nothing neutral, quarterly absent is the
    legal pre-augment shape per §3.2). RateLimited always propagates. The price leg goes
    through `ladder` (§5.2 --price-source); every other leg is Yahoo's alone."""
    fast = yf_fetch.fetch_fast_info(symbol, state_dir=state_dir)
    bars, splits, basis = price_bars(symbol, ladder, state_dir=state_dir)
    try:
        shares = yf_fetch.fetch_shares_full(symbol, state_dir=state_dir)
    except yf_fetch.RateLimited:
        raise
    except yf_fetch.FetchFailed:
        shares = None
    annual = yf_fetch.fetch_statements(symbol, state_dir=state_dir, freq="annual")
    quarterly = None
    if not annual_only:
        try:
            quarterly = yf_fetch.fetch_statements(symbol, state_dir=state_dir, freq="quarterly")
        except yf_fetch.RateLimited:
            raise
        except yf_fetch.FetchFailed:
            quarterly = None
    return build_cache_entry(symbol, meta, fast, bars, shares, annual, quarterly,
                             splits=splits, price_basis=basis)


def _set_aside_cache(cache_dir: Path) -> None:
    """--fresh (msg 62): move cache/ to cache-<YYYY-MM-DD>/ (suffix -2, -3 ... on collision)."""
    if not cache_dir.exists():
        return
    stamp = date.today().isoformat()
    dest, n = Path(f"{cache_dir}-{stamp}"), 2
    while dest.exists():
        dest = Path(f"{cache_dir}-{stamp}-{n}")
        n += 1
    cache_dir.rename(dest)
    print(f"--fresh: set existing cache aside as {dest}/")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Populate the fundamentals cache (§5.2).")
    ap.add_argument("--universe", default="universe.csv")
    ap.add_argument("--limit", type=int, default=None, help="first N symbols (smoke runs)")
    ap.add_argument("--only", default=None, help="comma-separated symbols (smoke runs)")
    ap.add_argument("--fresh", action="store_true", help="set cache/ aside as cache-<date>/ first")
    ap.add_argument("--annual-only", action="store_true", help="v1 path: skip quarterly statements")
    ap.add_argument("--max-age-days", type=float, default=3, help="skip cache entries younger than this")
    ap.add_argument("--pace", type=float, default=None, help="per-call spacing seconds -> yf_fetch.set_pace")
    ap.add_argument("--price-source", default=AUTO_SOURCE, choices=PRICE_SOURCES,
                    help="vendor behind the §3.2 price block: auto (yahoo, then the keyless "
                         "fallback once yahoo throttles), yahoo, or stockanalysis")
    args = ap.parse_args(argv)

    ladder = PriceLadder(args.price_source)
    cache_dir = Path("cache")
    if args.fresh:
        _set_aside_cache(cache_dir)
    cache_dir.mkdir(exist_ok=True)
    state_dir = cache_dir.resolve().parent
    if args.pace is not None:
        yf_fetch.set_pace(args.pace)

    rows = pd.read_csv(args.universe).to_dict("records")
    if args.only:
        wanted = {s.strip().upper() for s in args.only.split(",") if s.strip()}
        rows = [r for r in rows if str(r["symbol"]).upper() in wanted]
    if args.limit is not None:
        rows = rows[: args.limit]

    total, done, failed = len(rows), 0, 0
    fallback_priced, without_splits = 0, 0
    started_at = datetime.now(timezone.utc).isoformat()
    write_progress(PROGRESS_FILE, task="populate", total=total, done=done, failed=failed,
                   started_at=started_at)

    for row in rows:
        symbol = str(row["symbol"])
        path = cache_dir / cache_filename(symbol)
        if is_fresh(path, max_age_days=args.max_age_days, need_quarterly=not args.annual_only):
            done += 1
            write_progress(PROGRESS_FILE, task="populate", total=total, done=done,
                           failed=failed, started_at=started_at)
            continue
        try:
            entry = fetch_entry(symbol, row, state_dir, annual_only=args.annual_only,
                                ladder=ladder)
            atomic_write_json(path, entry)
            if entry["price_basis"] != pit.BASIS_RAW:
                fallback_priced += 1
                if not entry["splits"]:
                    without_splits += 1
            done += 1
        except ladder.rate_limited as e:
            failed += 1
            append_failure(FAILURES_FILE, symbol, f"rate-limited: {e}")
            write_progress(PROGRESS_FILE, task="populate", total=total, done=done,
                           failed=failed, started_at=started_at)
            print(f"{symbol}: rate-limited after the full backoff ladder — stopping the run",
                  file=sys.stderr)
            return 1
        except Exception as e:  # FetchFailed and raw yfinance errors alike: never fatal (§5.2)
            failed += 1
            append_failure(FAILURES_FILE, symbol, e)
        write_progress(PROGRESS_FILE, task="populate", total=total, done=done,
                       failed=failed, started_at=started_at)

    write_progress(PROGRESS_FILE, task="populate", total=total, done=done, failed=failed,
                   started_at=started_at, finished=True,
                   finished_at=datetime.now(timezone.utc).isoformat())
    print(f"populate finished: {done}/{total} cached, {failed} failures -> {cache_dir}/")
    if fallback_priced:
        print(f"LET OP: {fallback_priced} entries dragen koersbasis "
              f"'{ladder.fallback.basis}' (bron {ladder.fallback.name}) — voor een live run "
              f"is dat exact de vandaag verhandelde koers, dus hun marktkapitalisatie klopt; "
              f"{without_splits} daarvan zonder splitshistorie, waardoor de herrekening van "
              f"deviatie 8 stilvalt en een recente split als verwatering leest (§6.17).",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
