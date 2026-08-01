"""EDGAR point-in-time fetcher: companyfacts + weekly price grid (RECONSTRUCTION.md §5.8, §3.6).

python bt_fetch.py [--universe universe.csv] [--start 2020-01-01] [--limit N] [--only SYM,SYM]
                   [--price-source {auto,yahoo,stockanalysis}]

SEC company_tickers.json -> CIK map, cached once at bt_cache/company_tickers.json;
per symbol the raw companyfacts payload -> bt_cache/facts/<SYM>.json and the weekly
price grid (SPY first — it is the §5.10 rebalance clock — then the universe) ->
bt_cache/prices/<SYM>.json. Every EDGAR request carries the pinned User-Agent and
>=0.15 s spacing (§3.6, well under 8 req/s); Yahoo prices go through
vendor.yf_fetch.fetch_weekly_bars under the same box-wide pacing lock as populate.py, any
other vendor through pricesrc (--price-source below).

Two file-shape rules the backtest depends on:
- Every bar carries BOTH prices, {"close": raw, "adj_close": adjusted}. The adjusted
  close is retroactively rescaled by every later split/dividend, so a market cap built
  from it embeds the future; pit.py multiplies share counts by the close field — in the
  share terms the file declares — and keeps adj_close for total-return math. The
  vendored fetch_weekly_bars keeps only Adj Close
  and vendor/ is owned elsewhere, so the raw column is taken through bt_fetch's own paced
  call (weekly_frame) on the same lock/ladder — and simply reused when a future vendor
  version returns "close" itself. If the raw column cannot be had, the grid degrades to
  adjusted-only and the run says so.
- The TRUE symbol lives INSIDE both payloads, because the filename sanitizes '/' to '-'
  ("BRK/B" -> BRK-B.json) and the loader must map back to the universe symbol.

Price source (--price-source, §5.8): Yahoo is served by the raw+adjusted path above,
unchanged. Any other vendor comes from pricesrc, whose sources DECLARE the share terms of
their closes, and that declaration is written into every file as `price_basis` (§3.6) —
a "split_adjusted_today" grid is only a correct historical market cap because pit restates
the share count into the same terms, so the basis may never be guessed by a reader. Under
the default `auto`, a Yahoo rate limit retires the Yahoo leg and the run continues on the
fallback instead of stopping, which is the point on a 429'd box; grids from different
sources may sit side by side, each declaring its own basis. The keyless fallback has no
split feed, so its files carry no splits and the run reports how many (§6.17).

Resumable: existing files are never refetched (except legacy adjusted-only price grids,
which are refetched unless --keep-legacy-prices); failures land in failures.log and
progress.json carries task "bt_fetch" (§3.2 contract) so reporter.py works unchanged;
a RateLimited with no source left to fall back on stops the run exactly like populate.py.
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


def prices_payload(frame: pd.DataFrame, start: str, symbol: str | None = None,
                   splits: dict | None = None) -> dict:
    """Weekly YAHOO frame -> the §3.6 prices/<SYM>.json payload: the true symbol next to
    {"YYYY-MM-DD": {"close": raw, "adj_close": adjusted}} bars at/after start. A frame
    without a raw "close" column (or with a NaN in it) writes that bar adjusted-ONLY rather
    than pretending the adjusted value is a raw close — readers fall back to it anyway
    (pit.bar_value) but pit.grid_is_degraded can then still see the degradation.

    The basis DECLARED is the basis of what is actually in the file. With the raw column
    present that is "raw": Yahoo's Close is the price as it traded on the bar's own day.
    With NO bar carrying one — the shape this box writes whenever the supplementary raw
    call fails, and it fails for exactly the reason the fallback exists — every effective
    close is an Adj Close, i.e. restated into today's share terms, and declaring it "raw"
    would make pit skip the share restatement and understate every historical market cap by
    the split factor. So that file declares "split_adjusted_today", which is true of its
    splits; its closes carry a dividend adjustment on top, and `grid_is_degraded` is what
    reports THAT (the backtest discloses it). A partly-raw grid keeps "raw" — most bars are
    as-traded, and the degraded flag again covers the rest."""
    bars = {}
    has_close = "close" in frame.columns
    for ts, row in frame.iterrows():
        day = pd.Timestamp(ts).date().isoformat()
        if day < start:
            continue
        adj = float(row["adj_close"])
        raw = float(row["close"]) if has_close and not pd.isna(row["close"]) else None
        bars[day] = {"adj_close": adj} if raw is None else {"close": raw, "adj_close": adj}
    basis = (pit.BASIS_SPLIT_ADJUSTED_TODAY
             if bars and all("close" not in bar for bar in bars.values())
             else pit.BASIS_RAW)
    return pit.price_file(symbol, dict(sorted(bars.items())), splits, basis)


def _paced(state_dir: Path, fn):
    """One raw Yahoo call under vendor/yf_fetch's box-wide lock — through its rate-limit
    ladder when that private helper is present, else the public pacing context alone."""
    runner = getattr(yf_fetch, "_paced_call", None)
    if runner is not None:
        return runner(state_dir, fn)
    with yf_fetch.yahoo_pacing(state_dir):
        return fn()


def _raw_weekly_frame(symbol: str, *, state_dir: Path, period: str):
    """(RAW weekly Close series, {date: split ratio}) — or (None, {}) when Yahoo does not
    deliver a Close column. auto_adjust=False keeps Close next to Adj Close and
    actions=True carries the split events, so both ride ONE call; validation of the grid
    itself stays with the vendored fetch_weekly_bars."""
    def _raw():
        return yf.Ticker(symbol).history(period=period, interval="1wk",
                                         auto_adjust=False, actions=True)

    frame = _paced(state_dir, _raw)
    if frame is None or len(frame) == 0:
        return None, {}
    events = splits_payload(frame)
    if "Close" not in frame.columns:
        return None, events
    close = frame["Close"].astype(float)
    close = close[close.notna() & (close > 0)]
    close = close[~close.index.duplicated(keep="last")]   # reindex refuses duplicate labels
    return (close if len(close) else None), events


def splits_payload(frame) -> dict:
    """Yahoo's "Stock Splits" column -> the §3.6 {date: ratio} map through `pit.split_ratio`
    (0.0 on an ordinary week and an inert 1.0 both dropped — one filter for every writer of
    this map). Pure; a frame without the column yields {} (no splits known, never a fake
    ratio)."""
    if frame is None or "Stock Splits" not in getattr(frame, "columns", []):
        return {}
    out = {}
    for ts, raw in frame["Stock Splits"].items():
        ratio = pit.split_ratio(raw)
        if ratio is not None:
            out[pd.Timestamp(ts).date().isoformat()] = ratio
    return dict(sorted(out.items()))


def weekly_frame(symbol: str, *, state_dir: Path, period: str
                 ) -> tuple[pd.DataFrame, bool, dict]:
    """-> (frame with column adj_close and, when obtainable, close; degraded?; split
    events). The vendored, validated fetch_weekly_bars supplies adj_close (and close
    directly if a future vendor version returns it); otherwise the raw closes come from
    _raw_weekly_frame and are aligned onto the same bars — bars without one keep NaN
    rather than a fake raw close. degraded=True means at least one bar has no raw close of
    its own, so its market cap carries later split/dividend rescaling — disclose it.

    The split events ride whichever fetch produced the frame (both ask actions=True, so no
    extra Yahoo call): they let the backtest tell a 2:1 split from 100%/yr dilution, which
    would otherwise trip the §4.4 hard dilution veto at every tick (§6.14)."""
    frame = yf_fetch.fetch_weekly_bars(symbol, state_dir=state_dir, period=period)
    vendor_splits = splits_payload(frame)
    if "close" in frame.columns:
        return (frame.loc[:, ["close", "adj_close"]],
                bool(frame["close"].isna().any()), vendor_splits)
    out = frame.loc[:, ["adj_close"]].copy()
    try:
        raw, events = _raw_weekly_frame(symbol, state_dir=state_dir, period=period)
    except yf_fetch.RateLimited:   # a rate limit still stops the run (§5.8), never degrades
        raise
    except Exception:      # transport/shape failure on the supplementary call only
        raw, events = None, {}
    events = events or vendor_splits
    if raw is None:
        return out, True, events                # adjusted-only, and the payload says so
    aligned = raw.reindex(out.index)
    out["close"] = aligned
    return out.loc[:, ["close", "adj_close"]], bool(aligned.isna().any()), events


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


def price_payload(symbol: str, ladder: populate.PriceLadder, *, state_dir: Path,
                  start: str, period: str) -> dict:
    """The §3.6 prices/<SYM>.json payload for one symbol from the run's price ladder
    (§5.8 --price-source): bars, split events and the basis they are stated in.

    The Yahoo leg is weekly_frame, untouched — it is the only path that can supply a raw
    close per bar. A pricesrc source hands back the §3.6 bar map directly, together with
    its split feed ({} for the keyless ones: no events KNOWN, never a fake ratio) and its
    own declared basis, which is written into the file so a mixed cache stays readable."""
    if ladder.yahoo:
        try:
            frame, _degraded, splits = weekly_frame(symbol, state_dir=state_dir,
                                                    period=period)
        except Exception as e:
            ladder.yahoo_leg_failed(e)     # re-raises unless a fallback can take over
        else:
            return prices_payload(frame, start, symbol, splits)
    source = ladder.fallback
    return pit.price_file(symbol, source.weekly(symbol, start=start, state_dir=state_dir),
                          source.splits(symbol), source.basis)


def _stale(grid: dict, basis: str, *, refresh_legacy: bool, refresh_basis: bool) -> bool:
    """Should an existing §3.6 grid be refetched rather than kept? (§5.8 resumability.)

    - An EMPTY grid is not a finished symbol. It is what a delisted name whose last bar
      predates --start writes, and what a vendor hiccup writes, and the two are
      indistinguishable on disk — so it never counts as done.
    - A legacy adjusted-only grid is refetched (it cannot yield an uncontaminated market
      cap) unless the caller keeps it.
    - A non-raw grid is refetched only on request (--refresh-basis): it is a complete,
      correctly declared file, but it was written while Yahoo was throttling and a healthy
      Yahoo can now replace it with as-traded closes AND a split feed."""
    if not grid:
        return True
    if pit.grid_is_degraded(grid) and refresh_legacy:
        return True
    return basis != pit.BASIS_RAW and refresh_basis


def _fetch_prices(symbol: str, prices_dir: Path, ladder: populate.PriceLadder, *,
                  state_dir: Path, start: str, period: str,
                  refresh_legacy: bool = True, refresh_basis: bool = False) -> dict:
    """Weekly grid for one symbol -> bt_cache/prices/<SYM>.json (§3.6); resumable per
    `_stale`. Returns the §3.6 payload now standing for the symbol — the one just written,
    or the existing file normalized through the loader (so a legacy shape still answers for
    its bars, splits and declared basis) — and the caller reports on what it declares
    rather than on what the fetch happened to know.

    A file that will not load — corrupt JSON, or a basis declaration this version does not
    know — is treated as absent and REFETCHED. Letting the exception out here would count
    the symbol as a failure without ever rewriting the file, so every later run failed on
    it identically and the cache never healed itself."""
    path = prices_dir / populate.cache_filename(symbol)
    if path.exists():
        try:
            loaded = pit.load_price_file(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError) as e:
            print(f"{path.name} onleesbaar ({e}) — opnieuw ophalen", file=sys.stderr)
        else:
            _, grid, events = loaded
            if not _stale(grid, loaded.price_basis, refresh_legacy=refresh_legacy,
                          refresh_basis=refresh_basis):
                return pit.price_file(symbol, grid, events, loaded.price_basis)
    payload = price_payload(symbol, ladder, state_dir=state_dir, start=start, period=period)
    populate.atomic_write_json(path, payload)
    return payload


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
    ap.add_argument("--price-source", default=populate.AUTO_SOURCE,
                    choices=populate.PRICE_SOURCES,
                    help="weekly price vendor: auto (yahoo, then the keyless fallback once "
                         "yahoo throttles), yahoo, or stockanalysis; every grid records the "
                         "basis its closes are stated in (§3.6 price_basis)")
    args = ap.parse_args(argv)

    ladder = populate.PriceLadder(args.price_source)
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
    degraded, today_basis, without_splits = [], [], []
    started_at = datetime.now(timezone.utc).isoformat()
    populate.write_progress(populate.PROGRESS_FILE, task="bt_fetch", total=total,
                            done=done, failed=failed, started_at=started_at)

    for symbol in symbols:
        try:
            if symbol != "SPY":
                _fetch_facts(symbol, ciks, facts_dir)
            payload = _fetch_prices(symbol, prices_dir, ladder, state_dir=state_dir,
                                    start=args.start, period=period,
                                    refresh_legacy=not args.keep_legacy_prices)
            if pit.grid_is_degraded(payload[pit.BARS_KEY]):
                degraded.append(symbol)
            if payload[pit.BASIS_KEY] != pit.BASIS_RAW:
                today_basis.append(symbol)
                if not payload[pit.SPLITS_KEY]:
                    without_splits.append(symbol)
            done += 1
        except ladder.rate_limited as e:
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
    if today_basis:    # ook oudere bestanden uit een eerdere run tellen mee, niet alleen deze
        print(f"LET OP: {len(today_basis)} koersroosters staan in basis "
              f"'{pit.BASIS_SPLIT_ADJUSTED_TODAY}' — pit zet de aandelenaantallen in "
              f"dezelfde termen, dus de marktkapitalisatie klopt in dollars; "
              f"{len(without_splits)} daarvan zonder splitshistorie, en die herrekening kan "
              f"dan niet draaien (pit vlagt market_cap_split_unadjusted, §6.17).",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
