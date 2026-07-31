"""EDGAR point-in-time fetcher: companyfacts + weekly price grid (RECONSTRUCTION.md §5.8, §3.6).

python bt_fetch.py [--universe universe.csv] [--start 2020-01-01] [--limit N] [--only SYM,SYM]

SEC company_tickers.json -> CIK map, cached once at bt_cache/company_tickers.json;
per symbol the raw companyfacts payload -> bt_cache/facts/<SYM>.json and the weekly
adj-close grid (SPY first — it is the §5.10 rebalance clock — then the universe) ->
bt_cache/prices/<SYM>.json as {"YYYY-MM-DD": adj_close}. Every EDGAR request carries
the pinned User-Agent and >=0.15 s spacing (§3.6, well under 8 req/s); prices go through
vendor.yf_fetch.fetch_weekly_bars under the same box-wide pacing lock as populate.py.
Resumable: existing files are never refetched; failures land in failures.log and
progress.json carries task "bt_fetch" (§3.2 contract) so reporter.py works unchanged;
a RateLimited stops the run exactly like populate.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

import populate
from vendor import yf_fetch

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
USER_AGENT = "stock-agentcy scout (y.n.hanekamp@gmail.com)"
EDGAR_SPACING_SECONDS = 0.15    # §3.6: >=0.15 s between EDGAR requests
BT_DIR = Path("bt_cache")

_last_edgar = 0.0


def _edgar_get(url: str) -> bytes:
    """One paced EDGAR GET: waits out the §3.6 spacing, sends the pinned User-Agent."""
    global _last_edgar
    wait = EDGAR_SPACING_SECONDS - (time.monotonic() - _last_edgar)
    if wait > 0:
        time.sleep(wait)
    _last_edgar = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def cik_map(raw: dict) -> dict[str, int]:
    """SEC company_tickers.json payload ({"0": {cik_str, ticker, title}, ...}) ->
    {TICKER: cik} (§5.8)."""
    return {str(row["ticker"]).upper(): int(row["cik_str"]) for row in raw.values()}


def prices_payload(frame: pd.DataFrame, start: str) -> dict:
    """vendor.yf_fetch weekly frame -> the §3.6 {"YYYY-MM-DD": adj_close} grid at/after start."""
    out = {}
    for ts, px in frame["adj_close"].items():
        day = pd.Timestamp(ts).date().isoformat()
        if day >= start:
            out[day] = float(px)
    return dict(sorted(out.items()))


def yf_period(start: str, *, today: date | None = None) -> str:
    """Smallest valid yfinance period string covering start -> today (§5.8 weekly bars)."""
    years = ((today or date.today()) - date.fromisoformat(start)).days / 365.25
    for cap, period in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y")):
        if years < cap:
            return period
    return "max"


def _load_cik_map(path: Path) -> dict:
    """Cached SEC symbol->CIK map: downloaded once to bt_cache/company_tickers.json (§3.6)."""
    if not path.exists():
        populate.atomic_write_json(path, json.loads(_edgar_get(SEC_TICKERS_URL)))
    return cik_map(json.loads(path.read_text(encoding="utf-8")))


def _fetch_facts(symbol: str, ciks: dict, facts_dir: Path) -> None:
    """companyfacts for one symbol -> bt_cache/facts/<SYM>.json; an existing file is done
    (resumable, §5.8). No CIK (non-EDGAR listings like the .AS names) raises -> one
    failures.log line, never fatal."""
    path = facts_dir / populate.cache_filename(symbol)
    if path.exists():
        return
    cik = ciks.get(symbol.upper())
    if cik is None:
        raise LookupError("no SEC CIK mapping (not EDGAR-listed)")
    populate.atomic_write_json(path, json.loads(_edgar_get(FACTS_URL.format(cik=cik))))


def _fetch_prices(symbol: str, prices_dir: Path, state_dir: Path, start: str,
                  period: str) -> None:
    """Weekly adj-close grid for one symbol -> bt_cache/prices/<SYM>.json (§3.6); resumable."""
    path = prices_dir / populate.cache_filename(symbol)
    if path.exists():
        return
    frame = yf_fetch.fetch_weekly_bars(symbol, state_dir=state_dir, period=period)
    populate.atomic_write_json(path, prices_payload(frame, start))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="EDGAR companyfacts + weekly prices -> bt_cache/ (§5.8).")
    ap.add_argument("--universe", default="universe.csv")
    ap.add_argument("--start", default="2020-01-01", help="earliest weekly bar kept in the grid")
    ap.add_argument("--limit", type=int, default=None, help="first N symbols (smoke runs)")
    ap.add_argument("--only", default=None, help="comma-separated symbols (smoke runs)")
    args = ap.parse_args(argv)

    facts_dir, prices_dir = BT_DIR / "facts", BT_DIR / "prices"
    facts_dir.mkdir(parents=True, exist_ok=True)
    prices_dir.mkdir(parents=True, exist_ok=True)
    state_dir = BT_DIR.resolve().parent        # same box-wide yahoo lock as populate.py
    period = yf_period(args.start)
    ciks = _load_cik_map(BT_DIR / "company_tickers.json")

    rows = pd.read_csv(args.universe).to_dict("records")
    if args.only:
        wanted = {s.strip().upper() for s in args.only.split(",") if s.strip()}
        rows = [r for r in rows if str(r["symbol"]).upper() in wanted]
    if args.limit is not None:
        rows = rows[: args.limit]

    symbols = ["SPY"] + [str(r["symbol"]) for r in rows]   # the benchmark grid comes first
    total, done, failed = len(symbols), 0, 0
    started_at = datetime.now(timezone.utc).isoformat()
    populate.write_progress(populate.PROGRESS_FILE, task="bt_fetch", total=total,
                            done=done, failed=failed, started_at=started_at)

    for symbol in symbols:
        try:
            if symbol != "SPY":
                _fetch_facts(symbol, ciks, facts_dir)
            _fetch_prices(symbol, prices_dir, state_dir, args.start, period)
            done += 1
        except yf_fetch.RateLimited as e:
            failed += 1
            populate.append_failure(populate.FAILURES_FILE, symbol, f"rate-limited: {e}")
            populate.write_progress(populate.PROGRESS_FILE, task="bt_fetch", total=total,
                                    done=done, failed=failed, started_at=started_at)
            print(f"{symbol}: rate-limited after the full backoff ladder — stopping the run",
                  file=sys.stderr)
            return 1
        except Exception as e:  # missing CIKs, dead tickers, transport errors: never fatal (§5.8)
            failed += 1
            populate.append_failure(populate.FAILURES_FILE, symbol, e)
        populate.write_progress(populate.PROGRESS_FILE, task="bt_fetch", total=total,
                                done=done, failed=failed, started_at=started_at)

    populate.write_progress(populate.PROGRESS_FILE, task="bt_fetch", total=total, done=done,
                            failed=failed, started_at=started_at, finished=True,
                            finished_at=datetime.now(timezone.utc).isoformat())
    print(f"bt_fetch finished: {done}/{total} fetched, {failed} failures -> {BT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
