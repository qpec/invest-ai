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

from vendor import yf_fetch

PROGRESS_FILE = "progress.json"
FAILURES_FILE = "failures.log"
STATEMENT_TYPES = ("income", "balance", "cashflow")
# The bar fetch doubles as the split-history fetch (§3.2 "splits"): one history call,
# widened to cover the cached share series, instead of a second Yahoo request.
PRICE_PERIOD = "5y"


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
                      *, fetched_at: datetime | None = None,
                      splits: dict | None = None) -> dict:
    """Assemble one cache/<SYM>.json payload per §3.2 — pure and JSON-serializable
    with allow_nan=False. `quarterly` None -> the key is absent (pre-augment shape).
    `splits` defaults to the split events carried by the bar frame (§3.2 "splits"): the
    scoring layer needs them to restate the raw share series in today's share terms, so a
    split does not read as dilution (§4.3)."""
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


# ------------------------------------------------------------------- fetch pass

def fetch_entry(symbol: str, meta: dict, state_dir: Path, *, annual_only: bool) -> dict:
    """One symbol's full paced fetch (§5.2). fast_info, daily bar and annual
    statements are required; shares and quarterly degrade on FetchFailed (shares ->
    {} keeps the M leg computable-from-nothing neutral, quarterly absent is the
    legal pre-augment shape per §3.2). RateLimited always propagates."""
    fast = yf_fetch.fetch_fast_info(symbol, state_dir=state_dir)
    bars = yf_fetch.fetch_daily_bars(symbol, state_dir=state_dir, period=PRICE_PERIOD)
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
    return build_cache_entry(symbol, meta, fast, bars, shares, annual, quarterly)


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
    args = ap.parse_args(argv)

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
            entry = fetch_entry(symbol, row, state_dir, annual_only=args.annual_only)
            atomic_write_json(path, entry)
            done += 1
        except yf_fetch.RateLimited as e:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
