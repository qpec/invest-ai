"""Owner-exported SEC fact CSVs -> §4.1 Bundles, through `pit.as_of_bundle` (§3.6/§5.9).

The export (its own `README.txt` next to the data) flattens exactly the EDGAR companyfacts
payloads `bt_fetch.py` caches as `bt_cache/facts/<SYM>.json` (§3.6) into two long CSVs:

- `selected_sec_fact_observations.csv` — one row per observation
  (`symbol,namespace,tag,label,unit,start,end,filed,form,fy,fp,frame,value`), i.e. the
  companyfacts `units[<unit>][]` array with its `facts[<namespace>][<tag>]` address spelled
  out on every row. 3.07M rows / 418 MB, so it is only ever read with pandas `chunksize`.
- `sec_facts_tag_index_part{1,2,3}.csv` — one row per (symbol, tag) with the LATEST
  observation only, covering every tag the filer has, including several the observation file
  does not carry as a series (`AssetsCurrent`, `LiabilitiesCurrent`, `ShortTermBorrowings`,
  `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`).

This module is a serialization adapter and nothing more. It reshapes those rows back into
the raw companyfacts structure and hands them to `pit.as_of_bundle`, so every rule that
matters — filed-date discipline, the §5.9 tag fallback chains, YTD-minus-prior-cumulative
quarter derivation, gross-profit derivation, the debt carry-forward, the multi-class share
handling — is pit.py's, unchanged and untouched. Nothing here re-implements a single one of
them; a bug fixed in pit.py is fixed here for free.

**No price data in this export.** The manifest lists `weekly_prices.csv` but the file was
not shipped, so by default every bundle carries `price = None` and therefore
`market_cap = None`, and no price is invented. That is not a cosmetic gap: per
docs/SCORECARD-DESIGN.md §4.1 ("no price, no verdict") a price-less run is a **quality
profile only and explicitly NOT a verdict** — quality on its own is already fairly priced by
the market, so the output must never be read as a buy signal. `scoring.score_universe` says
the same thing in its own vocabulary: without a market cap the valuation metrics are
uncomputable and the name grades INSUFFICIENT. Pass `--prices weekly_prices.csv` (the file
the owner's own box does have) and the §3.6 grid reaches `pit.as_of_bundle`, market_cap
becomes computable and the names grade for real.

Three further honest limitations of this serialization, none of them fixable here:

- **The selected tag list has no D&A, and therefore no EBITDA.** The observation file
  carries 19 tags; `DepreciationDepletionAndAmortization` is not one of them (it appears in
  the tag index as a single point, which is a flow and therefore inert — see below). §5.9
  builds EBITDA as EBIT + D&A, so EBITDA is uncomputable for every name in this export,
  which makes net debt/EBITDA — a §4.6 REQUIRED metric — None and suspends the name as
  INSUFFICIENT *even when prices are supplied*. Re-export with D&A (and, for the ~40% of
  tickers that never tag `GrossProfit`, a cost-of-revenue tag) to lift that ceiling.

- **Tag-index rows are single points, not series.** Folding one is enough for a
  latest-balance metric (current ratio, working capital, NCI) and for nothing else: it has no
  `start`, so pit's flow path (which requires one) ignores it — no growth, no trend, no TTM
  contribution can ever come from it. See `merge_tag_index`. It also makes the run
  `as_of`-sensitive in a way a full series is not: the one point carries the LATEST filing's
  date, so an `as_of` before that filing hides it entirely. Measured on the full export,
  current assets reach the latest balance date for 77.7% of names at `--as-of 2026-06-29`
  and 97.6% at 2026-08-01. Run at (or after) the newest filing unless a historical tick is
  the point.
- **No split events.** §3.6 splits ride the Yahoo bar fetch, which this export does not
  contain, so `splits` is `{}` for every name. As-reported dei share counts are therefore
  NOT restated into as_of's share terms, and a name that split inside the share-trend window
  reads as dilution (§6.14) — which the §4.4 hard dilution veto can act on. Such a VETOED is
  an artifact of the missing split feed, not a finding.

CLI:

    python secsv.py --data-dir <dir> [--as-of 2026-06-29] [--only SYM,SYM] [--limit N]
                    [--universe universe.csv] [--prices weekly_prices.csv]
                    [--out bundles.jsonl]

`--out` writes one JSON bundle per line so a downstream run never re-parses the 418 MB.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import date

import pandas as pd

import pit

OBSERVATIONS_FILE = "selected_sec_fact_observations.csv"
TAG_INDEX_GLOB = "sec_facts_tag_index*.csv"
DEFAULT_CHUNKSIZE = 500_000          # ~0.9 GB peak over the full 3.07M-row export

# The observation columns this adapter needs; `label`/`fy`/`fp`/`frame` are export
# metadata companyfacts itself does not put in the unit entries, so they are not read.
OBS_COLUMNS = ("symbol", "namespace", "tag", "unit", "start", "end", "filed", "form", "value")
TAG_INDEX_COLUMNS = ("symbol", "namespace", "tag", "latest_unit", "latest_end",
                     "latest_filed", "latest_form", "latest_value")

DEFAULT_NAMESPACE = "us-gaap"         # a row with a blank namespace is a us-gaap row
DEFAULT_UNIT = "USD"

# The only tags a tag-index row can ever reach, because a tag-index row is a single point
# with no `start`: pit reads a startless entry through `_latest_filed(..., instant=True)`
# alone, and the one place that runs is `_balance_maps`. The simple chains are read out of
# pit's own table so they cannot drift; the second group is the debt / incl-NCI composition
# that `_balance_maps` spells out inline, and the third is the dei share tag.
_PIT_EXTRA_INSTANT_TAGS = (
    "LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent", "ShortTermBorrowings",
    # Lease-inclusive and combined-total debt concepts (2026-08-05): Comcast reports all
    # $90bn of its debt under DebtAndCapitalLeaseObligations and nothing under the four
    # tags above, which made it read as DEBT-FREE.
    "DebtAndCapitalLeaseObligations", "DebtLongtermAndShorttermCombinedAmount",
    "LongTermDebtAndCapitalLeaseObligations", "DebtCurrent",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
INSTANT_TAGS = frozenset(
    tag for chain in pit._BALANCE_CONCEPTS.values() for tag in chain
).union(_PIT_EXTRA_INSTANT_TAGS, {pit._SHARES_TAG})

# pit's point-disclosure chains (§3.6's refinancing wall, §3.7's concentration flag). The
# observations file carries only 19 curated tags and neither of these is among them, so
# without this fold both probes are unmeasurable for every name in the export — which is
# exactly what they were. Folded they reach `pit.disclosures` and NOTHING else: a
# disclosure tag is not in _BALANCE_CONCEPTS, so it cannot enter the balance section.
DISCLOSURE_TAGS = frozenset(
    tag for chain in pit._DISCLOSURE_CONCEPTS.values() for tag in chain)
# Registry-v2 supplement POINTS (goodwill, intangibles, liabilities, retained earnings):
# the bulk export's tag index carries these instants for most of the universe (measured
# 2026-08-03: Goodwill 1,580 filers, RetainedEarningsAccumulatedDeficit 1,893), so
# folding them lifts goodwill_pct_assets and Altman Z from tier-2-only to tier-1.
SUPPLEMENT_POINT_TAGS = frozenset(
    tag for chain in pit._SUPPLEMENT_POINT_CONCEPTS.values() for tag in chain)
FOLDED_TAGS = INSTANT_TAGS | DISCLOSURE_TAGS | SUPPLEMENT_POINT_TAGS

# --prices column inference: normalized (lowercased, non-alphanumerics dropped) names.
_SYMBOL_ALIASES = ("symbol", "ticker", "sym")
_DATE_ALIASES = ("date", "day", "week", "weekend", "weekending", "weekended",
                 "periodend", "period", "timestamp", "datetime", "bardate", "asof")
_CLOSE_ALIASES = ("close", "rawclose", "closeraw", "closeprice", "priceclose",
                  "unadjustedclose", "closeunadjusted")
_ADJ_ALIASES = ("adjclose", "adjustedclose", "adjclosingprice", "adjustedclosingprice",
                "closeadj", "closeadjusted", "adjustedprice", "adjustedcloseprice")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


# --------------------------------------------------------------------- small helpers

def _float(text) -> float | None:
    """CSV cell -> float, or None for blanks, non-numerics and NaN (a NaN would poison
    every comparison downstream and cannot be serialized with allow_nan=False)."""
    try:
        val = float(text)
    except (TypeError, ValueError):
        return None
    return None if val != val else val


def _normalize(name: str) -> str:
    """Column name -> comparison key: lowercase, alphanumerics only ('Adj Close' ->
    'adjclose', so every spelling of one column collapses onto the same key)."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _pick(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    """The first column whose normalized name is one of `aliases`, or None."""
    normalized = {_normalize(col): col for col in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def _chunks(path: Path, columns: tuple[str, ...], chunksize: int):
    """Stream `path` in `chunksize`-row blocks, yielding one list per requested column
    (plain Python strings, blanks kept as ''). Never materializes the whole file, and
    fails loudly — naming what it did find — when a required column is missing."""
    header = pd.read_csv(path, nrows=0)
    missing = [col for col in columns if col not in header.columns]
    if missing:
        raise ValueError(
            f"{path.name}: missing required column(s) {missing}; "
            f"found {list(header.columns)}")
    for chunk in pd.read_csv(path, usecols=list(columns), chunksize=chunksize,
                             dtype=str, keep_default_na=False):
        yield [chunk[col].tolist() for col in columns]


# --------------------------------------------------------------- observations -> facts

def symbols_in(data_dir: str | Path, chunksize: int = DEFAULT_CHUNKSIZE) -> list[str]:
    """Distinct symbols in the observation file, in file order — read from the symbol
    column alone, so `--limit N` costs a couple of seconds instead of a full parse."""
    path = Path(data_dir) / OBSERVATIONS_FILE
    seen, order = set(), []
    for (column,) in _chunks(path, ("symbol",), chunksize):
        for symbol in column:
            if symbol not in seen:
                seen.add(symbol)
                order.append(symbol)
    return order


def load_facts(data_dir: str | Path, symbols=None,
               chunksize: int = DEFAULT_CHUNKSIZE) -> dict[str, dict]:
    """The observation CSV -> {symbol: raw companyfacts payload}, streamed in chunks.

    Each payload is the exact structure `pit._unit_entries` reads (and `bt_cache/facts/
    <SYM>.json` stores, §3.6), so it is a drop-in for that cache file:

        {"cik": None, "entityName": None, "symbol": SYM,
         "facts": {"us-gaap": {TAG: {"label": TAG, "units": {"USD": [entry, ...]}}},
                   "dei":     {TAG: {"label": TAG, "units": {"shares": [entry, ...]}}}}}

    with `entry = {"start": ..., "end": ..., "filed": ..., "form": ..., "val": float}`.
    The `namespace` column decides the taxonomy verbatim (`us-gaap`, `dei`, and the handful
    of `ifrs-full` rows, which pit simply never looks at); `unit` stays the unit key, so
    pit's USD-then-shares preference and the non-USD filers both behave exactly as they do
    on a real companyfacts payload. A row with a blank `start` is an INSTANT and gets no
    `start` key at all — never the string "nan", which would read as a real period start
    and let a balance figure masquerade as a flow.

    `cik`/`entityName` are None because the export does not carry them; nothing in pit
    reads them. The `symbol` annotation is the §3.6 one (`pit.facts_symbol`).

    Rows with an unparseable value, or no `end`/`filed`, are dropped: pit would refuse them
    anyway (`_latest_filed`), and dropping them here keeps peak memory down. `symbols`
    (any iterable) filters while streaming. Measured on the full 3.07M-row / 418 MB export:
    ~15 s wall, ~0.9 GB peak RSS at the default chunksize.
    """
    path = Path(data_dir) / OBSERVATIONS_FILE
    wanted = None if symbols is None else set(symbols)
    intern = sys.intern
    facts: dict[str, dict] = {}
    for columns in _chunks(path, OBS_COLUMNS, chunksize):
        for symbol, namespace, tag, unit, start, end, filed, form, value in zip(*columns):
            if wanted is not None and symbol not in wanted:
                continue
            if not tag or not end or not filed:
                continue
            val = _float(value)
            if val is None:
                continue
            payload = facts.get(symbol)
            if payload is None:
                payload = facts[symbol] = {"cik": None, "entityName": None,
                                           pit.SYMBOL_KEY: symbol, "facts": {}}
            taxonomy = payload["facts"].setdefault(intern(namespace or DEFAULT_NAMESPACE), {})
            concept = taxonomy.get(tag)
            if concept is None:
                concept = taxonomy[intern(tag)] = {"label": tag, "units": {}}
            entry = {"end": intern(end), "filed": intern(filed),
                     "form": intern(form), "val": val}
            if start:                      # blank start == instant: no key at all
                entry["start"] = intern(start)
            concept["units"].setdefault(intern(unit or DEFAULT_UNIT), []).append(entry)
    return facts


def merge_tag_index(facts: dict[str, dict], data_dir: str | Path, symbols=None,
                    chunksize: int = DEFAULT_CHUNKSIZE,
                    tags: frozenset | set | None = FOLDED_TAGS) -> dict[str, dict]:
    """Fold the tag-index's latest-observation rows into `facts` for tags the observation
    file carries no series for. Mutates and returns `facts`.

    Each folded tag becomes a unit array of exactly ONE entry —
    `{"end": latest_end, "filed": latest_filed, "form": latest_form, "val": latest_value}`
    — which is a legitimate companyfacts shape and is read by pit like any other.

    **This is deliberately only enough for latest-balance metrics and point disclosures,
    and nothing more.** A single point has no `start`, so pit's flow path
    (`_latest_filed(..., instant=False)`, which skips any entry without one) cannot see it:
    no quarterly series, no annual series, no growth, no trend, no TTM contribution can ever
    be derived from a folded tag. What it does buy is real and was otherwise missing:
    `AssetsCurrent`/`LiabilitiesCurrent` (~97% of tickers, and the inputs to Working Capital
    and therefore to ROIC — a §4.6 REQUIRED metric, so without this fold nearly every name
    suspends), `ShortTermBorrowings` for the §5.9 debt composition, the incl-NCI equity tag
    Minority Interest is derived from, and pit's two `_DISCLOSURE_CONCEPTS` chains — the
    twelve-month debt maturity (~66% of these filers) and the concentration percentage
    (~11%), neither of which the observations file carries a series for, and both of which
    the inversion layer could therefore measure for exactly ZERO names before this.

    `tags` is that reachable set (`FOLDED_TAGS`, read out of pit's own concept tables).
    Folding a FLOW tag (`CostOfRevenue`, `ProfitLoss`, `DepreciationDepletionAnd-
    Amortization`, ...) is not wrong, just provably inert — and the export carries ~880k of
    them, half a gigabyte of concepts nothing can ever read. Pass `tags=None` to fold every
    tag anyway (verified on the full export to produce byte-identical bundles).

    A tag already present in the observations is NEVER touched — a real series always wins
    over a single point, and the same guard makes the fold idempotent across the three
    part-files. Only symbols already in `facts` are augmented: a symbol with no series at
    all cannot produce an annual income period and `pit.as_of_bundle` would return None for
    it however many single points it were handed.
    """
    wanted = None if symbols is None else set(symbols)
    for path in sorted(Path(data_dir).glob(TAG_INDEX_GLOB)):
        for columns in _chunks(path, TAG_INDEX_COLUMNS, chunksize):
            for symbol, namespace, tag, unit, end, filed, form, value in zip(*columns):
                if wanted is not None and symbol not in wanted:
                    continue
                if tags is not None and tag not in tags:
                    continue
                payload = facts.get(symbol)
                if payload is None or not tag or not end or not filed:
                    continue
                val = _float(value)
                if val is None:
                    continue
                taxonomy = payload["facts"].setdefault(namespace or DEFAULT_NAMESPACE, {})
                if tag in taxonomy:                 # a real series always wins
                    continue
                taxonomy[tag] = {"label": tag, "units": {(unit or DEFAULT_UNIT): [
                    {"end": end, "filed": filed, "form": form, "val": val}]}}
    return facts


# ------------------------------------------------------------------- prices (optional)

def load_prices(path: str | Path, chunksize: int = DEFAULT_CHUNKSIZE) -> dict[str, dict]:
    """`weekly_prices.csv` -> the §3.6 price grid `{symbol: {"YYYY-MM-DD": bar}}` that
    `pit.as_of_bundle`/`pit.price_at` already consume, where a bar is
    `{"close": raw, "adj_close": adjusted}`.

    The export's exact column spelling is not pinned anywhere, so the symbol, date and
    price columns are inferred from the obvious spellings (`symbol`/`ticker`, `date`,
    `close`/`Close`, `adj_close`/`Adj Close`/`adjusted_close`, compared case- and
    punctuation-insensitively). Inference never guesses silently: a file whose symbol,
    date, or both price columns cannot be identified raises ValueError naming every column
    actually found.

    When only ONE price column exists it is written under its own field only. That is
    pit's own model of a degraded grid: `pit.bar_value` falls back to the other field, so
    the one value stands for both, and `pit.grid_is_degraded` reports True for an
    adjusted-only grid — market caps built on it carry every later split and dividend and
    the caller must disclose it (§3.6). A raw-close-only grid is fine for market cap and
    merely lacks total-return math.
    """
    path = Path(path)
    header = pd.read_csv(path, nrows=0)
    found = list(header.columns)
    symbol_col = _pick(found, _SYMBOL_ALIASES)
    date_col = _pick(found, _DATE_ALIASES)
    close_col = _pick(found, _CLOSE_ALIASES)
    adj_col = _pick(found, _ADJ_ALIASES)
    problems = []
    if symbol_col is None:
        problems.append(f"no symbol column (looked for {list(_SYMBOL_ALIASES)})")
    if date_col is None:
        problems.append(f"no date column (looked for {list(_DATE_ALIASES)})")
    if close_col is None and adj_col is None:
        problems.append(f"no close or adjusted-close column (looked for "
                        f"{list(_CLOSE_ALIASES)} / {list(_ADJ_ALIASES)})")
    if problems:
        raise ValueError(f"{path.name}: cannot read as a §3.6 price grid — "
                         f"{'; '.join(problems)}. Columns found: {found}")

    columns = tuple(col for col in (symbol_col, date_col, close_col, adj_col)
                    if col is not None)
    fields = tuple(field for field, col in (("close", close_col), ("adj_close", adj_col))
                   if col is not None)          # aligned with columns[2:]
    grid: dict[str, dict] = {}
    day_cache: dict[str, str | None] = {}
    for block in _chunks(path, columns, chunksize):
        symbols, days, prices = block[0], block[1], block[2:]
        for row in zip(symbols, days, *prices):
            symbol, raw_day = row[0], row[1]
            if not symbol:
                continue
            day = day_cache.get(raw_day, ...)
            if day is ...:
                day = day_cache[raw_day] = _iso_day(raw_day)
            if day is None:
                continue
            bar = {field: value for field, value in zip(fields, (
                _float(cell) for cell in row[2:])) if value is not None}
            if bar:
                grid.setdefault(symbol, {})[day] = bar
    return grid


def _iso_day(text: str) -> str | None:
    """A date cell -> 'YYYY-MM-DD'. Plain ISO (with or without a time part) is sliced;
    anything else goes through pandas once, and unparseable cells are dropped."""
    text = (text or "").strip()
    if _ISO_DATE.match(text):
        return text[:10]
    if not text:
        return None
    try:
        return pd.Timestamp(text).date().isoformat()
    except (ValueError, TypeError):
        return None


def degraded_price_symbols(grid: dict) -> list[str]:
    """Symbols whose §3.6 grid has no raw close of its own — market caps built on them are
    split/dividend-contaminated and the caller must say so (`pit.grid_is_degraded`)."""
    return sorted(sym for sym, bars in (grid or {}).items() if pit.grid_is_degraded(bars))


# ---------------------------------------------------------------------- meta + bundles

def load_universe_meta(path: str | Path) -> dict[str, dict]:
    """`universe.csv` (§3.1) -> {symbol: {"name", "sector", "industry"}} for the Bundle's
    meta block. The export carries no sector/industry of its own, and a guessed sector is
    worse than none (it picks the §4.6 percentile cohort and the tier), so without this
    join the bundles' meta stays None — stated, never invented."""
    frame = pd.read_csv(path)
    if "symbol" not in frame.columns:
        raise ValueError(f"{Path(path).name}: no 'symbol' column (§3.1); "
                         f"found {list(frame.columns)}")
    meta = {}
    for row in frame.to_dict("records"):
        symbol = str(row["symbol"])
        meta[symbol] = {key: (None if (value := row.get(key)) is None or value != value
                              else value)
                        for key in ("name", "sector", "industry")}
    return meta


def bundles(data_dir: str | Path, as_of, symbols=None, meta=None, prices=None,
            chunksize: int = DEFAULT_CHUNKSIZE, use_tag_index: bool = True) -> list[dict]:
    """The export -> a list of §4.1 Bundles as they were knowable on `as_of`.

    Every bundle is built by `pit.as_of_bundle`; this function only assembles its inputs.
    Names for which pit returns None (no annual income period visible at `as_of` — a
    pre-first-10-K filer, or one whose series the export does not carry) are dropped.
    Order is the order of `symbols` when given, otherwise the export's own (alphabetical)
    order.

    `meta` is {symbol: {"name", "sector", "industry"}} (see `load_universe_meta`); a symbol
    without a row gets meta None rather than a guessed sector. `prices` is either a
    prepared §3.6 grid or a path to a `weekly_prices.csv` (`load_prices`); without one the
    grid is empty, so `price` and `market_cap` are None and the run is a quality profile,
    NOT a verdict (SCORECARD-DESIGN.md §4.1). `splits` is always {} — the export has none.
    """
    facts = load_facts(data_dir, symbols=symbols, chunksize=chunksize)
    if use_tag_index:
        merge_tag_index(facts, data_dir, symbols=symbols, chunksize=chunksize)
    if prices is None or isinstance(prices, dict):
        grid = prices or {}
    else:
        grid = load_prices(prices, chunksize=chunksize)
    meta = meta or {}
    order = [s for s in symbols if s in facts] if symbols is not None else list(facts)
    out = []
    for symbol in order:
        bundle = pit.as_of_bundle(facts[symbol], symbol, meta.get(symbol), as_of, grid)
        if bundle is not None:
            out.append(bundle)
    return out


def write_jsonl(rows: list[dict], path: str | Path) -> Path:
    """One JSON bundle per line, so a downstream run never re-parses the 418 MB export."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    return path


def read_jsonl(path: str | Path) -> list[dict]:
    """The `--out` file back into a list of §4.1 Bundles."""
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# ------------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="SEC CSV export -> §4.1 Bundles via pit.as_of_bundle (§5.9)")
    ap.add_argument("--data-dir", required=True, help="directory holding the export CSVs")
    ap.add_argument("--as-of", default=date.today().isoformat(),
                    help="point-in-time date; facts filed after it do not exist")
    ap.add_argument("--only", default=None, help="comma-separated symbols")
    ap.add_argument("--limit", type=int, default=None, help="first N symbols")
    ap.add_argument("--universe", default=None,
                    help="universe.csv (§3.1) to join sector/industry from")
    ap.add_argument("--prices", default=None,
                    help="weekly_prices.csv; without it market_cap is None and the run is "
                         "a quality profile, not a verdict (SCORECARD-DESIGN.md §4.1)")
    ap.add_argument("--out", default=None, help="write bundles as JSONL to this path")
    ap.add_argument("--chunksize", type=int, default=DEFAULT_CHUNKSIZE)
    ap.add_argument("--no-tag-index", action="store_true",
                    help="skip the tag-index fold (no AssetsCurrent/LiabilitiesCurrent)")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    if not (data_dir / OBSERVATIONS_FILE).exists():
        print(f"{data_dir / OBSERVATIONS_FILE} ontbreekt", file=sys.stderr)
        return 1

    symbols = None
    if args.only:
        symbols = [s.strip() for s in args.only.split(",") if s.strip()]
    if args.limit is not None:
        symbols = (symbols or symbols_in(data_dir, args.chunksize))[:args.limit]

    meta = load_universe_meta(args.universe) if args.universe else None
    if meta is None:
        print("geen --universe: sector/industry blijven None (niet geraden) — de §4.6 "
              "sectorpercentielen vallen daardoor terug op de 'None'-cohort.",
              file=sys.stderr)

    grid = load_prices(args.prices, args.chunksize) if args.prices else {}
    if not grid:
        print("geen --prices: market_cap/price blijven None — dit is een KWALITEITSPROFIEL, "
              "geen verdict (SCORECARD-DESIGN.md §4.1: kwaliteit-op-zich is al eerlijk "
              "geprijsd).", file=sys.stderr)
    else:
        degraded = degraded_price_symbols(grid)
        if degraded:
            print(f"LET OP: {len(degraded)} koersroosters zonder ruwe close — "
                  f"marktkapitalisatie draagt latere splits/dividenden (§3.6).",
                  file=sys.stderr)

    rows = bundles(data_dir, args.as_of, symbols=symbols, meta=meta, prices=grid,
                   chunksize=args.chunksize, use_tag_index=not args.no_tag_index)
    priced = sum(1 for row in rows if row.get("market_cap") is not None)
    print(f"{len(rows)} bundles @ {args.as_of} "
          f"({priced} met market_cap, {len(rows) - priced} zonder)")
    if args.out:
        print(f"geschreven: {write_jsonl(rows, args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
