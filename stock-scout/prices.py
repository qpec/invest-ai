"""The §3.6 weekly price grid, refreshed on a schedule (`prices.py refresh`).

Every consumer of the grid — the scorecard's valuation pillar, the site build, the
monitor, the desk UI — reads a directory of `<SYMBOL>.json` files written by
`pit.write_price_file`'s envelope. Nothing in the repo ever WROTE that directory: the
grid was seeded once by hand and then silently aged. That is the same defect shape as
the 2026-08-05 share-count bug read from the other side — a fresh share count times a
months-old close is a fabrication in exactly the way a stale count times a fresh close
is — except that here the number keeps looking plausible because prices move slowly.

So this module is the missing producer, and it is deliberately shaped like
`enrich.rolling_refresh`, which solves the same problem for filings:

  * thesis names first, always. A monitored holding's price must be the newest thing on
    disk before any monitor run; the budget may never cut it.
  * then the stalest, so a universe expansion converges over a few nights instead of
    needing one enormous fetch.
  * a fetch that fails leaves the previous file exactly as it was and is COUNTED. A
    vendor outage must degrade the grid's age, never its contents.

The price basis is recorded per file (`pricesrc` declares it), because a
split-adjusted-today close and an as-traded close are the same number today and wildly
different numbers in a backtest — `pit.checked_basis` raises rather than assume.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import pit

DEFAULT_SOURCE = "auto"
# Weekly bars: a grid refreshed within ~2 bars is current, and anything past that is a
# schedule that has stopped running. Deliberately not the same knob as the staleness
# REFUSAL in pit (PRICE_MAX_AGE_DAYS) — this one decides what to re-fetch, that one
# decides what may become a market cap, and they must be free to differ.
DEFAULT_MAX_AGE_DAYS = 10.0
DEFAULT_BUDGET = 800


def _universe_symbols(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [s for row in csv.DictReader(handle)
                if (s := (row.get("symbol") or "").strip().upper())]


def thesis_symbols(theses_dir: Path | None) -> list[str]:
    """Committed + draft thesis names. These lead the queue unconditionally: the monitor
    grades them against pre-committed triggers, and a trigger tested on a stale price is
    worse than one reported UNCHECKED."""
    if theses_dir is None:
        return []
    out = []
    for sub in ("committed", "drafts"):
        for path in sorted(Path(theses_dir, sub).glob("*.json")):
            out.append(path.stem.upper())
    return list(dict.fromkeys(out))


def newest_bar(path: Path) -> str | None:
    """The last day this file carries, or None when it is absent/unreadable. Read from the
    contents rather than the mtime: a re-write that fetched nothing new must not read as
    fresh, and that is precisely what a rate-limited vendor produces."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    bars = payload.get(pit.BARS_KEY) or {}
    return max(bars) if bars else None


def _age_days(day: str | None, today: str) -> float:
    if day is None:
        return float("inf")
    from datetime import date
    try:
        return date.fromisoformat(today).toordinal() - date.fromisoformat(day).toordinal()
    except ValueError:
        return float("inf")


def refresh(grid_dir: Path, universe_symbols, *, priority=(), budget: int = DEFAULT_BUDGET,
            max_age_days: float = DEFAULT_MAX_AGE_DAYS, source: str = DEFAULT_SOURCE,
            today: str | None = None, log=print) -> dict:
    """Refresh the stalest slice of the grid. Returns the counters, never raises for a
    per-symbol failure — a sweep that aborts on the first delisted ticker refreshes
    nothing, which is the worst of both outcomes."""
    import pricesrc                      # lazy: the vendor import is optional at rest
    from datetime import date

    grid_dir = Path(grid_dir)
    grid_dir.mkdir(parents=True, exist_ok=True)
    today = today or date.today().isoformat()
    vendor = pricesrc.get(source)

    ages = {}
    for sym in {s.upper() for s in universe_symbols} | {p.upper() for p in priority}:
        ages[sym] = _age_days(newest_bar(grid_dir / f"{sym}.json"), today)

    head = [s.upper() for s in priority if s.upper() in ages]
    seen = set(head)
    # Stalest first; a symbol with no file at all is infinitely stale and leads the rest.
    rest = sorted((s for s in ages if s not in seen), key=lambda s: -ages[s])
    plan = head + [s for s in rest if ages[s] > max_age_days][:max(0, budget - len(head))]

    fetched = failed = 0
    problems: list[str] = []
    for sym in plan:
        try:
            bars = vendor.weekly(sym)
            if not bars:
                raise pricesrc.FetchFailed("no bars")
            splits = vendor.splits(sym)
        except Exception as error:                      # noqa: BLE001 - vendor-agnostic
            failed += 1
            problems.append(f"{sym}: {type(error).__name__}: {error}")
            continue
        payload = {pit.SYMBOL_KEY: sym, pit.BARS_KEY: bars, "splits": splits,
                   "source": getattr(vendor, "name", source),
                   "price_basis": getattr(vendor, "price_basis", None),
                   "fetched": today}
        tmp = grid_dir / f"{sym}.json.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, grid_dir / f"{sym}.json")       # the file is old or new, never half
        fetched += 1

    after = [_age_days(newest_bar(p), today) for p in grid_dir.glob("*.json")]
    oldest = max(after) if after else float("inf")
    log(f"prices: {fetched} fetched, {failed} failed, "
        f"{len(ages) - len(plan)} already fresh (<= {max_age_days:g}d); "
        f"grid holds {len(after)} symbols, oldest bar {oldest:g}d old")
    for line in problems[:20]:
        log(f"  !! {line}")
    if len(problems) > 20:
        log(f"  !! ... and {len(problems) - 20} more")
    return {"fetched": fetched, "failed": failed, "planned": len(plan),
            "symbols": len(after), "oldest_age_days": oldest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("refresh", help="fetch the stalest slice of the price grid")
    run.add_argument("--grid", required=True, help="the <SYMBOL>.json price directory")
    run.add_argument("--universe", default="universe.csv")
    run.add_argument("--theses-dir", help="thesis names lead the queue")
    run.add_argument("--symbols", help="comma-separated; overrides --universe")
    run.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    run.add_argument("--max-age-days", type=float, default=DEFAULT_MAX_AGE_DAYS)
    run.add_argument("--source", default=DEFAULT_SOURCE)
    run.add_argument("--as-of", default=None, help="treat this as today (tests/backfill)")

    status = sub.add_parser("status", help="report the grid's age without fetching")
    status.add_argument("--grid", required=True)
    status.add_argument("--as-of", default=None)

    args = parser.parse_args(argv)
    grid = Path(args.grid)

    if args.cmd == "status":
        from datetime import date
        today = args.as_of or date.today().isoformat()
        ages = sorted((_age_days(newest_bar(p), today), p.stem) for p in grid.glob("*.json"))
        if not ages:
            print(f"{grid}: empty — every market cap will be absent (no price, no verdict)")
            return 1
        print(f"{grid}: {len(ages)} symbols, newest bar {ages[0][0]:g}d old, "
              f"oldest {ages[-1][0]:g}d old ({ages[-1][1]})")
        stale = sum(1 for age, _ in ages if age > pit.PRICE_MAX_AGE_DAYS)
        print(f"  {stale} past the {pit.PRICE_MAX_AGE_DAYS}d refusal bound — "
              f"their market caps are reported absent, not stale")
        return 0

    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               if args.symbols else _universe_symbols(Path(args.universe)))
    priority = thesis_symbols(Path(args.theses_dir) if args.theses_dir else None)
    out = refresh(grid, symbols, priority=priority, budget=args.budget,
                  max_age_days=args.max_age_days, source=args.source, today=args.as_of)
    # A sweep that fetched nothing it planned to is a broken vendor, not a quiet success.
    return 1 if out["planned"] and not out["fetched"] else 0


if __name__ == "__main__":
    sys.exit(main())
