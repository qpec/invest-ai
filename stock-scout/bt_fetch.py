"""EDGAR point-in-time fetcher: companyfacts + weekly price grid (RECONSTRUCTION.md §5.8, §3.6).

python bt_fetch.py [--universe universe.csv] [--start 2020-01-01] [--limit N] [--only SYM,SYM]

SEC company_tickers.json -> CIK map, cached once at bt_cache/company_tickers.json;
per symbol the raw companyfacts payload -> bt_cache/facts/<SYM>.json and the weekly
price grid (SPY first — it is the §5.10 rebalance clock — then the universe) ->
bt_cache/prices/<SYM>.json. Every EDGAR request carries the pinned User-Agent and
>=0.15 s spacing (§3.6, well under 8 req/s); prices go through
vendor.yf_fetch.fetch_weekly_bars under the same box-wide pacing lock as populate.py.

Two file-shape rules the backtest depends on:
- Every bar carries BOTH prices, {"close": raw, "adj_close": adjusted}. The adjusted
  close is retroactively rescaled by every later split/dividend, so a market cap built
  from it embeds the future; pit.py multiplies share counts by the RAW close and keeps
  adj_close for total-return math. The vendored fetch_weekly_bars keeps only Adj Close
  and vendor/ is owned elsewhere, so the raw column is taken through bt_fetch's own paced
  call (weekly_frame) on the same lock/ladder — and simply reused when a future vendor
  version returns "close" itself. If the raw column cannot be had, the grid degrades to
  adjusted-only and the run says so.
- The TRUE symbol lives INSIDE both payloads, because the filename sanitizes '/' to '-'
  ("BRK/B" -> BRK-B.json) and the loader must map back to the universe symbol.

Resumable: existing files are never refetched (except legacy adjusted-only price grids,
which are refetched unless --keep-legacy-prices); failures land in failures.log and
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
import yfinance as yf

import pit
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


def prices_payload(frame: pd.DataFrame, start: str, symbol: str | None = None) -> dict:
    """Weekly frame -> the §3.6 prices/<SYM>.json payload: the true symbol next to
    {"YYYY-MM-DD": {"close": raw, "adj_close": adjusted}} bars at/after start. A frame
    without a raw "close" column (or with a NaN in it) writes that bar adjusted-ONLY rather
    than pretending the adjusted value is a raw close — readers fall back to it anyway
    (pit.bar_value) but pit.grid_is_degraded can then still see the degradation."""
    bars = {}
    has_close = "close" in frame.columns
    for ts, row in frame.iterrows():
        day = pd.Timestamp(ts).date().isoformat()
        if day < start:
            continue
        adj = float(row["adj_close"])
        raw = float(row["close"]) if has_close and not pd.isna(row["close"]) else None
        bars[day] = {"adj_close": adj} if raw is None else {"close": raw, "adj_close": adj}
    return pit.price_file(symbol, dict(sorted(bars.items())))


def _paced(state_dir: Path, fn):
    """One raw Yahoo call under vendor/yf_fetch's box-wide lock — through its rate-limit
    ladder when that private helper is present, else the public pacing context alone."""
    runner = getattr(yf_fetch, "_paced_call", None)
    if runner is not None:
        return runner(state_dir, fn)
    with yf_fetch.yahoo_pacing(state_dir):
        return fn()


def _raw_weekly_closes(symbol: str, *, state_dir: Path, period: str) -> pd.Series | None:
    """The RAW (unadjusted) weekly Close series, or None when Yahoo does not deliver one.
    auto_adjust=False keeps Close next to Adj Close; only this column is taken — validation
    of the grid itself stays with the vendored fetch_weekly_bars."""
    def _raw():
        return yf.Ticker(symbol).history(period=period, interval="1wk",
                                         auto_adjust=False, actions=True)

    frame = _paced(state_dir, _raw)
    if frame is None or len(frame) == 0 or "Close" not in frame.columns:
        return None
    close = frame["Close"].astype(float)
    close = close[close.notna() & (close > 0)]
    return close if len(close) else None


def weekly_frame(symbol: str, *, state_dir: Path, period: str) -> tuple[pd.DataFrame, bool]:
    """-> (frame with column adj_close and, when obtainable, close; degraded?). The
    vendored, validated fetch_weekly_bars supplies adj_close (and close directly if a
    future vendor version returns it); otherwise the raw closes come from
    _raw_weekly_closes and are aligned onto the same bars — bars without one keep NaN
    rather than a fake raw close. degraded=True means at least one bar has no raw close of
    its own, so its market cap carries later split/dividend rescaling — disclose it."""
    frame = yf_fetch.fetch_weekly_bars(symbol, state_dir=state_dir, period=period)
    if "close" in frame.columns:
        return frame.loc[:, ["close", "adj_close"]], bool(frame["close"].isna().any())
    out = frame.loc[:, ["adj_close"]].copy()
    try:
        raw = _raw_weekly_closes(symbol, state_dir=state_dir, period=period)
    except Exception:      # transport/shape failure on the supplementary call only
        raw = None
    if raw is None:
        return out, True                        # adjusted-only, and the payload says so
    aligned = raw.reindex(out.index)
    out["close"] = aligned
    return out.loc[:, ["close", "adj_close"]], bool(aligned.isna().any())


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
    """companyfacts for one symbol -> bt_cache/facts/<SYM>.json, annotated with the true
    symbol (the filename sanitizes '/'); an existing file is done (resumable, §5.8). No CIK
    (non-EDGAR listings like the .AS names) raises -> one failures.log line, never fatal."""
    path = facts_dir / populate.cache_filename(symbol)
    if path.exists():
        return
    cik = ciks.get(symbol.upper())
    if cik is None:
        raise LookupError("no SEC CIK mapping (not EDGAR-listed)")
    payload = json.loads(_edgar_get(FACTS_URL.format(cik=cik)))
    payload[pit.SYMBOL_KEY] = symbol
    populate.atomic_write_json(path, payload)


def _fetch_prices(symbol: str, prices_dir: Path, state_dir: Path, start: str,
                  period: str, *, refresh_legacy: bool = True) -> bool:
    """Weekly raw+adjusted grid for one symbol -> bt_cache/prices/<SYM>.json (§3.6);
    resumable. A legacy adjusted-only grid is refetched (it cannot yield an uncontaminated
    market cap) unless refresh_legacy is off. Returns True when the written grid is
    degraded (no raw closes available)."""
    path = prices_dir / populate.cache_filename(symbol)
    if path.exists():
        _, grid = pit.load_price_file(json.loads(path.read_text(encoding="utf-8")))
        stale = bool(grid) and pit.grid_is_degraded(grid)
        if not (stale and refresh_legacy):
            return stale
    frame, degraded = weekly_frame(symbol, state_dir=state_dir, period=period)
    populate.atomic_write_json(path, prices_payload(frame, start, symbol))
    return degraded


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="EDGAR companyfacts + weekly prices -> bt_cache/ (§5.8).")
    ap.add_argument("--universe", default="universe.csv")
    ap.add_argument("--start", default="2020-01-01", help="earliest weekly bar kept in the grid")
    ap.add_argument("--limit", type=int, default=None, help="first N symbols (smoke runs)")
    ap.add_argument("--only", default=None, help="comma-separated symbols (smoke runs)")
    ap.add_argument("--keep-legacy-prices", action="store_true",
                    help="keep adjusted-only price grids instead of refetching them "
                         "(they cannot yield an uncontaminated PIT market cap)")
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
    degraded = []
    started_at = datetime.now(timezone.utc).isoformat()
    populate.write_progress(populate.PROGRESS_FILE, task="bt_fetch", total=total,
                            done=done, failed=failed, started_at=started_at)

    for symbol in symbols:
        try:
            if symbol != "SPY":
                _fetch_facts(symbol, ciks, facts_dir)
            if _fetch_prices(symbol, prices_dir, state_dir, args.start, period,
                             refresh_legacy=not args.keep_legacy_prices):
                degraded.append(symbol)
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
    if degraded:
        print(f"LET OP: {len(degraded)} koersroosters zonder ruwe close "
              f"({', '.join(degraded[:5])}{'...' if len(degraded) > 5 else ''}) — hun "
              f"marktkapitalisatie draagt latere splits/dividenden; de backtest meldt dit "
              f"in zijn disclosures.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
