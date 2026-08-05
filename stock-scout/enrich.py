"""Hardened metric fetching — a tiered fallback chain with provenance (owner-directed,
2026-08-03: "if the current possibilities don't allow for a full enrichment, there should
be a secondary method or maybe a third cherry method").

The bulk SEC CSV export is a *selection* of tags. When a registry metric comes back n/a,
the cause is usually a concept the export simply does not carry — CROX's net_debt_to_ebitda
was the canonical case: a real, filed number the packet could not see. The chain:

    tier 1  "sec-export"   the bulk CSV export (secsv.load_facts) — what we already have
    tier 2  "edgar-live"   SEC EDGAR companyfacts, per symbol — MORE of the same filings
    tier 3  "vendor-yf"    yfinance aggregates — a DIFFERENT KIND of number entirely

Three rules make the chain safe rather than merely bigger:

- **Fill only what is missing.** A tag already present in the export is never touched by
  tier 2; a lower tier can never override a higher one. Both tiers are as-filed XBRL, so
  where they overlap they agree anyway — the rule exists so that a disagreement, if one
  ever appears, is impossible to smuggle in silently.
- **Point-in-time survives the merge.** EDGAR companyfacts entries carry `filed`, and the
  merge happens on the raw payload BEFORE `pit.as_of_bundle` applies its `filed <= as_of`
  filter — so an enriched backtest bundle still cannot see the future. This is why tier 2
  merges facts and lets `scoring.evaluate` recompute, rather than injecting a computed
  metric: arithmetic stays in one place, and the PIT filter stays in front of it.
- **Vendor numbers never enter scoring.** Tier 3 values are not filed facts: no `filed`
  date, no accession, restated at the vendor's whim. They are returned in a separate
  display-only structure, labelled, for a human reading a packet or a dashboard — never
  merged into `facts`, never seen by `scoring.evaluate`, never able to fire a trigger.

Usage (the site build and the thesis packet both call this):

    python enrich.py --sec-data <dir> --cache enrich_cache            # everything with gaps
    python enrich.py --sec-data <dir> --symbols CROX --cache enrich_cache

Tests are fully offline (R15): the EDGAR transport is injectable and the vendor import is
guarded, so the suite never opens a socket.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
import urllib.request
from pathlib import Path

import pit
import scoring

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
USER_AGENT = "stock-agentcy scout (y.n.hanekamp@gmail.com)"
EDGAR_SPACING_SECONDS = 0.15          # SEC fair-use: stay well under 10 req/s

TIER_EXPORT = "sec-export"
TIER_EDGAR = "edgar-live"
TIER_VENDOR = "vendor-yf"

# The provenance ledger a payload carries after enrichment: {"us-gaap:Tag": tier}.
ENRICHMENT_KEY = "enrichment"

_last_request = 0.0


def _edgar_get(url: str) -> bytes:
    """One paced EDGAR GET (bt_fetch's convention: pinned User-Agent, spaced requests)."""
    global _last_request
    wait = EDGAR_SPACING_SECONDS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def cik_map(transport=_edgar_get) -> dict[str, int]:
    """{TICKER: cik} from the SEC's own ticker map."""
    raw = json.loads(transport(SEC_TICKERS_URL))
    return {str(row["ticker"]).upper(): int(row["cik_str"]) for row in raw.values()}


def cik_map_cached(cache_dir: Path, transport=_edgar_get,
                   max_age_days: int | None = None) -> dict[str, int]:
    """The ticker map, disk-cached beside the companyfacts cache — so an offline site
    rebuild that only ever hits the cache needs zero network. Written atomically, and a
    corrupt file (an interrupted first run) falls through to a fresh fetch instead of
    poisoning every later run — .exists() alone would have believed the truncation.

    `max_age_days` is the staleness valve for callers that hold network anyway (the
    refresh jobs): older than that, refetch — but a failed refetch degrades to the
    stale copy, never kills the sweep. Offline consumers leave it None: a newly listed
    ticker they cannot see is tomorrow night's problem, not a build failure."""
    import os
    import time
    cached = Path(cache_dir) / "_tickers.json"
    stale_fallback = None
    if cached.exists():
        try:
            mapping = {k: int(v) for k, v in
                       json.loads(cached.read_text(encoding="utf-8")).items()}
            age_days = (time.time() - os.path.getmtime(cached)) / 86400
            if max_age_days is None or age_days <= max_age_days:
                return mapping
            stale_fallback = mapping
        except (json.JSONDecodeError, ValueError, AttributeError, OSError):
            pass
    try:
        mapping = cik_map(transport)
    except Exception:  # noqa: BLE001 — a stale map must degrade, not kill the job
        if stale_fallback is not None:
            return stale_fallback
        raise
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mapping), encoding="utf-8")
    os.replace(tmp, cached)
    return mapping


def fetch_companyfacts(cik: int, *, transport=_edgar_get,
                       cache_dir: Path | None = None, refresh: bool = False) -> dict:
    """One symbol's companyfacts payload, disk-cached so a re-run costs nothing.

    The cache is per-CIK and dated inside the payload (`_fetched`); staleness is the
    caller's policy, not this function's — filings do not un-file, so an old cache is
    incomplete at worst, never wrong. `refresh=True` is that policy's lever: skip the
    cache read and refetch now (the rolling-freshness jobs). What lands on disk is the
    PRUNED payload — the tag selection the pipeline can actually read — because a full
    companyfacts document runs 2–8 MB and a universe of thousands would outgrow both
    the box's memory and its backup volume for tags no consumer can reach."""
    if cache_dir is not None:
        cached = Path(cache_dir) / f"CIK{cik:010d}.json"
        if cached.exists() and not refresh:
            return json.loads(cached.read_text(encoding="utf-8"))
    payload = json.loads(transport(FACTS_URL.format(cik=cik)))
    payload["_fetched"] = _dt.date.today().isoformat()
    payload = prune_payload(payload)
    if cache_dir is not None:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        import os
        os.replace(tmp, cached)
    return payload


# --- the consumed-tag selection (what a payload is allowed to weigh) ------------------

def consumed_tags() -> dict[str, frozenset[str]]:
    """Every (namespace, tag) the PIT layer can ever read — introspected from pit's own
    concept tables (plus secsv's documented inline-read extras), not copied, so a new
    concept chain widens this set automatically. Nothing outside it is reachable by any
    consumer: pit resolves tags exclusively through these chains, and scoring/registry
    read bundles, never facts."""
    import secsv
    us_gaap: set[str] = set()
    for table in (pit._INCOME_CONCEPTS, pit._CASHFLOW_CONCEPTS, pit._BALANCE_CONCEPTS,
                  pit._SUPPLEMENT_FLOW_CONCEPTS, pit._SUPPLEMENT_POINT_CONCEPTS,
                  pit._DISCLOSURE_CONCEPTS):
        for chain in table.values():
            us_gaap.update(chain)
    us_gaap.update(secsv._PIT_EXTRA_INSTANT_TAGS)
    return {"us-gaap": frozenset(us_gaap), "dei": frozenset({pit._SHARES_TAG})}


# History horizon for pruned payloads. Tag selection alone is not enough at scale: a
# consumed tag drags two decades of quarterly entries (~850 KB/name measured raw).
# ANNUAL series keep FULL depth — post-dedupe that is ~1 entry/year/tag, essentially
# free, and the growth anchors (_revenue_growth, _per_share_ofcf_growth,
# probe_predictability) read the OLDEST point, so truncating them changes scores
# (preflight review 2026-08-05). Only sub-annual history is cut: TTM derivation and
# persistence streaks need a few recent years of 10-Q chains, nothing older.
QUARTERLY_HORIZON_YEARS = 5
_ANNUAL_FORMS = ("10-K", "20-F", "40-F")


def prune_payload(payload: dict) -> dict:
    """A companyfacts payload cut to the consumed-tag selection, one latest-filed entry
    per period, and a sub-annual history horizon — the same idea the bulk export always
    was: a curated SELECTION, not the whole taxonomy. Non-facts keys (cik, entityName,
    _fetched, symbol, enrichment) pass through untouched.

    Order matters (preflight review 2026-08-05): the latest-filed winner per period is
    chosen across ALL forms FIRST — restatements ride 8-Ks, and filtering by form before
    the dedupe let a superseded 10-K value win (GOOG FY2013 OCF, reproduced live). Only
    then is the horizon applied, by PERIOD SPAN, never by filing form. The dei share tag
    is exempt from both horizon and dedupe: shares_series detects inconsistent filings
    by grouping the raw entries per filed date, and its whole history is a few KB."""
    keep = consumed_tags()
    today = _dt.date.today()
    quarterly_cutoff = f"{today.year - QUARTERLY_HORIZON_YEARS}-01-01"

    def slim_entry(entry: dict) -> dict | None:
        # Minimal-entry normalization: exactly the five fields pit reads (and the
        # export loader emits) — accn/fy/fp/frame are dead weight at this scale.
        end, filed = entry.get("end"), entry.get("filed")
        if not end or not filed or entry.get("val") is None:
            return None
        slim = {"end": end, "filed": filed, "form": str(entry.get("form") or ""),
                "val": entry["val"]}
        if entry.get("start"):
            slim["start"] = entry["start"]
        return slim

    def keep_period(key: tuple, annual_form_seen: bool) -> bool:
        start, end = key
        if start is not None:
            try:
                if pit._days(start, end) >= pit.ANNUAL_MIN_DAYS:
                    return True                      # annual span: full depth
            except ValueError:
                return False                         # unparseable dates: refuse
            return end >= quarterly_cutoff
        # Instants have no span; an annual filing's balance points keep full depth
        # (~1/year), everything else follows the sub-annual horizon.
        return annual_form_seen or end >= quarterly_cutoff

    pruned = {k: v for k, v in payload.items() if k != "facts"}
    facts: dict = {}
    for namespace, tags in (payload.get("facts") or {}).items():
        wanted = keep.get(namespace)
        if not wanted:
            continue
        kept = {}
        for tag, concept in tags.items():
            if tag not in wanted:
                continue
            shares_exempt = namespace == "dei" and tag == pit._SHARES_TAG
            units = {}
            for unit, entries in (concept.get("units") or {}).items():
                if shares_exempt:
                    trimmed = [s for e in entries if (s := slim_entry(e))]
                    if trimmed:
                        units[unit] = trimmed
                    continue
                by_period: dict = {}
                annual_seen: dict = {}
                for raw in entries:
                    slim = slim_entry(raw)
                    if slim is None:
                        continue
                    key = (slim.get("start"), slim["end"])
                    annual_seen[key] = (annual_seen.get(key, False)
                                        or slim["form"].startswith(_ANNUAL_FORMS))
                    best = by_period.get(key)
                    # >= mirrors _latest_filed's tie-break: among equal filed
                    # dates the later list entry wins in both places.
                    if best is None or slim["filed"] >= best["filed"]:
                        by_period[key] = slim
                survivors = [entry for key, entry in by_period.items()
                             if keep_period(key, annual_seen[key])]
                if survivors:
                    units[unit] = sorted(survivors,
                                         key=lambda e: (e["end"], e["filed"]))
            if units:
                kept[tag] = {**{k: v for k, v in concept.items() if k != "units"},
                             "units": units}
        if kept:
            facts[namespace] = kept
    pruned["facts"] = facts
    return pruned


def merge_payload(base: dict, extra: dict, *, source: str = TIER_EDGAR) -> list[str]:
    """Fill tags MISSING from `base` with tags from `extra`; return what was added.

    Tag-level, deliberately: a tag the export already carries is left exactly as it is,
    even if the live payload has more entries for it — mixing two sources inside one
    concept's entry list would make "where did this number come from" unanswerable, and
    provenance is the whole point. Every added tag is stamped in base["enrichment"]."""
    added = []
    ledger = base.setdefault(ENRICHMENT_KEY, {})
    base_facts = base.setdefault("facts", {})
    for namespace, concepts in (extra.get("facts") or {}).items():
        have = base_facts.setdefault(namespace, {})
        for tag, concept in concepts.items():
            if tag in have:
                continue
            have[tag] = concept
            ledger[f"{namespace}:{tag}"] = source
            added.append(f"{namespace}:{tag}")
    return added


def registry_metrics(bundle: dict) -> dict[str, float | None]:
    """Every thesis-registry value for one bundle — the numbers a trigger may test."""
    import thesis
    evaluated = thesis.registry_evaluate(bundle)
    return {name: thesis.metric_value(name, bundle, evaluated) for name in thesis.METRICS}


def gaps(bundle: dict) -> list[str]:
    """Registry metrics this bundle cannot compute — the reason to try the next tier."""
    return [name for name, value in registry_metrics(bundle).items() if value is None]


def enrich_payloads(facts: dict[str, dict], symbols: list[str], *,
                    transport=_edgar_get, cache_dir: Path | None = None,
                    ciks: dict[str, int] | None = None,
                    log=print) -> dict[str, list[str]]:
    """Tier 2 over a set of symbols: fetch each one's live companyfacts and fill the
    export's missing tags in place. Returns {symbol: [added tags]}. A symbol the SEC
    ticker map does not know is reported and skipped — never guessed."""
    ciks = ciks if ciks is not None else cik_map(transport)
    added_by_symbol: dict[str, list[str]] = {}
    for symbol in symbols:
        cik = ciks.get(symbol.upper())
        if cik is None:
            log(f"{symbol}: not in the SEC ticker map — skipped, not guessed")
            continue
        if symbol not in facts:
            log(f"{symbol}: not in the export — skipped (enrichment fills gaps, it does "
                f"not invent filers)")
            continue
        try:
            live = fetch_companyfacts(cik, transport=transport, cache_dir=cache_dir)
        except Exception as error:  # noqa: BLE001 — one dead fetch must not kill the sweep
            log(f"{symbol}: EDGAR fetch failed ({type(error).__name__}: {error}) — "
                f"this name stays un-enriched and says so")
            continue
        added_by_symbol[symbol] = merge_payload(facts[symbol], live)
    return added_by_symbol


# --- cache bootstrap + rolling freshness (2026-08-05, owner-directed expansion) -------
#
# The export is a snapshot; the universe is not. A symbol the export has never heard of
# can still be scored honestly: a cached companyfacts payload IS the payload shape the
# whole pipeline reads (secsv.load_facts documents the equivalence), every tag it
# carries is stamped edgar-live in the provenance ledger, and PIT discipline survives
# because companyfacts entries carry their own `filed` dates. Bootstrap is ADDITIVE
# ONLY: a symbol the export already knows is never touched, so the frozen decision
# layer stays bit-identical for the original universe.

def bootstrap_payloads(facts: dict[str, dict], symbols, *, cache_dir: Path,
                       ciks: dict[str, int] | None = None, transport=_edgar_get,
                       cache_only: bool = False, log=print) -> dict[str, int]:
    """Create payloads for symbols absent from the export. Returns {symbol: tag count}.

    `cache_only=True` is the offline consumers' mode (weekly monitor, site build):
    the cache is read, the network never — a name with no cache entry yet simply
    stays absent until a refresh job has fetched it, and the caller reports how many
    are still pending. Never merges into an existing payload."""
    ciks = ciks if ciks is not None else cik_map_cached(Path(cache_dir), transport)
    made: dict[str, int] = {}
    for symbol in symbols:
        sym = str(symbol).upper()
        if sym in facts:                      # additive only — the export stays frozen
            continue
        cik = ciks.get(sym)
        if cik is None:
            continue                          # not an SEC filer — nothing to bootstrap
        if cache_only and not (Path(cache_dir) / f"CIK{cik:010d}.json").exists():
            continue                          # pending a refresh job; caller counts it
        try:
            payload = fetch_companyfacts(cik, transport=transport, cache_dir=cache_dir)
        except Exception as error:  # noqa: BLE001 — one dead fetch must not kill a sweep
            log(f"{sym}: EDGAR fetch failed ({type(error).__name__}: {error}) — "
                f"stays absent and says so")
            continue
        payload = prune_payload(payload)      # older caches may still hold full payloads
        ledger = {f"{namespace}:{tag}": TIER_EDGAR
                  for namespace, tags in (payload.get("facts") or {}).items()
                  for tag in tags}
        if not ledger:
            continue                          # a filer with zero readable tags: unscoreable
        payload["symbol"] = sym
        payload[ENRICHMENT_KEY] = ledger
        facts[sym] = payload
        made[sym] = len(ledger)
    return made


def bootstrap_bundles(symbols, *, cache_dir: Path, ciks: dict[str, int],
                      as_of, meta: dict | None = None, prices: dict | None = None,
                      log=print) -> tuple[list[dict], int]:
    """Streaming bootstrap for the whole-universe consumers (site build, picks): each
    cached payload becomes its bundle IMMEDIATELY and is freed — a parsed payload runs
    ~370 KB resident (measured), so thousands must never coexist; a bundle is a
    several-fold smaller derived map. Cache-only by construction: these callers are
    offline. Returns (bundles, pending) where pending counts SEC filers still awaiting
    their first refresh fetch — reported, never guessed. The few-name payload variant
    (the monitor's committed set) stays `bootstrap_payloads`."""
    cache_dir = Path(cache_dir)
    bundles: list[dict] = []
    pending = 0
    seen: set[str] = set()
    for symbol in symbols:
        sym = str(symbol).upper()
        if sym in seen:
            continue
        seen.add(sym)
        cik = ciks.get(sym)
        if cik is None:
            continue                          # not an SEC filer — nothing to bootstrap
        path = cache_dir / f"CIK{cik:010d}.json"
        if not path.exists():
            pending += 1
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            log(f"{sym}: corrupt cache entry ({type(error).__name__}) — stays absent")
            continue
        payload = prune_payload(payload)      # older caches may still hold full payloads
        payload["symbol"] = sym
        bundle = pit.as_of_bundle(payload, sym, (meta or {}).get(sym), as_of,
                                  prices or {})
        if bundle is not None:
            bundles.append(bundle)
    return bundles, pending


def thesis_symbols(theses_dir: Path) -> list[str]:
    """Committed first, then drafts — the freshness priority order. Tolerates both
    artifact shapes (committed/<SYM>.json files, drafts/<SYM>/ directories)."""
    ordered: list[str] = []
    for sub in ("committed", "drafts"):
        base = Path(theses_dir) / sub
        if not base.exists():
            continue
        for path in sorted(base.iterdir()):
            if path.name.startswith("monitor-"):
                continue                      # the weekly spool lives beside the drafts
            if path.is_dir() or path.suffix == ".json":
                sym = (path.stem if path.suffix else path.name).upper()
                if sym not in ordered:
                    ordered.append(sym)
    return ordered


def rolling_refresh(cache_dir: Path, universe_symbols, *, priority=(),
                    budget: int = 1500, transport=_edgar_get, log=print) -> dict:
    """The freshness sweep: priority names are ALWAYS refetched first (monitored
    theses must be the newest thing on disk before any monitor run), then the stalest
    cache entries fill the remaining budget. Staleness = cache-file mtime; a symbol
    with no cache file at all is infinitely stale and leads the queue, which is what
    makes a universe expansion converge to full coverage over a few nights."""
    import os
    cache_dir = Path(cache_dir)
    # The refresh jobs hold network by design — they are where a newly listed
    # ticker enters the map. A week keeps the map fresher than any filing cadence.
    ciks = cik_map_cached(cache_dir, transport, max_age_days=7)

    def mtime(sym: str) -> float:
        path = cache_dir / f"CIK{ciks[sym]:010d}.json"
        try:
            return os.path.getmtime(path)
        except OSError:
            return float("-inf")

    head = [s.upper() for s in priority if s.upper() in ciks]
    seen = set(head)
    rest = sorted((s for s in (str(u).upper() for u in universe_symbols)
                   if s in ciks and s not in seen), key=mtime)
    unknown = sum(1 for u in universe_symbols if str(u).upper() not in ciks)
    plan = head + rest[:max(0, budget - len(head))]
    ok = failed = 0
    for sym in plan:
        try:
            fetch_companyfacts(ciks[sym], transport=transport,
                               cache_dir=cache_dir, refresh=True)
            ok += 1
        except Exception as error:  # noqa: BLE001
            failed += 1
            log(f"{sym}: refresh failed ({type(error).__name__}: {error})")
    return {"refreshed": ok, "failed": failed, "planned": len(plan),
            "priority": len(head), "universe": len(list(universe_symbols)),
            "not_sec_filers": unknown}


def universe_symbols_csv(path: Path) -> list[str]:
    """The symbol column of a universe.csv, order preserved."""
    import csv
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return [row["symbol"].upper() for row in csv.DictReader(fh) if row.get("symbol")]


VENDOR_FILE = "vendor.json"


def _default_ticker_info(symbol: str) -> dict:
    """Live yfinance lookup. Guarded import: yfinance is one of the four runtime
    packages but is not importable in every environment this code runs in (the research
    sandbox's proxy resets its TLS fingerprint). Absence degrades honestly to {}."""
    try:
        import yfinance  # noqa: PLC0415 — the guard IS the point
        return yfinance.Ticker(symbol).info or {}
    except Exception:  # noqa: BLE001
        return {}


def vendor_metrics(symbol: str, *, ticker_info=_default_ticker_info) -> dict[str, dict]:
    """Tier 3, the cherry: vendor aggregates shaped like registry metrics, for DISPLAY
    next to an n/a — never scoring. Every value is labelled with its tier and a note
    saying exactly what it is not: filed. `ticker_info` is injectable so tests never
    open a socket (R15)."""
    info = ticker_info(symbol)
    if not info:
        return {}
    out: dict[str, dict] = {}

    def put(name, value):
        if value is not None:
            out[name] = {"v": round(float(value), 2), "source": TIER_VENDOR,
                         "note": "vendor aggregate — unfiled, display-only, never scored"}

    debt, cash, ebitda = (info.get(k) for k in ("totalDebt", "totalCash", "ebitda"))
    if debt is not None and cash is not None and ebitda:
        put("net_debt_to_ebitda", (debt - cash) / ebitda)
    if info.get("grossMargins") is not None:
        put("gross_margin_pct", info["grossMargins"] * 100.0)
    return out


def write_vendor(cache_dir: Path, by_symbol: dict[str, dict]) -> Path:
    import os
    path = Path(cache_dir) / VENDOR_FILE
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(by_symbol, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_vendor(cache_dir: Path) -> dict[str, dict]:
    path = Path(cache_dir) / VENDOR_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sec-data", help="bulk export dir (gap-fill mode only)")
    parser.add_argument("--symbols", help="comma-separated; default: every name with a "
                                          "registry-metric gap")
    parser.add_argument("--as-of", default=_dt.date.today().isoformat())
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--prices")
    parser.add_argument("--cache", default="enrich_cache")
    parser.add_argument("--theses-dir", help="theses/ — its names lead every refresh")
    parser.add_argument("--rolling", type=int, metavar="BUDGET",
                        help="freshness-sweep mode: refetch thesis names first, then "
                             "the stalest cache entries, up to BUDGET fetches")
    parser.add_argument("--force-refresh", action="store_true",
                        help="with --symbols: refetch those names NOW, cache or not — "
                             "the pre-monitor freshness pass")
    parser.add_argument("--out", help="write enriched bundles JSONL here")
    parser.add_argument("--vendor", action="store_true",
                        help="tier 3: fetch vendor display values for metrics still "
                             "n/a after tier 2 (never scored; needs yfinance)")
    args = parser.parse_args(argv)

    if args.rolling is not None:
        priority = thesis_symbols(Path(args.theses_dir)) if args.theses_dir else []
        summary = rolling_refresh(
            Path(args.cache), universe_symbols_csv(Path(args.universe)),
            priority=priority, budget=args.rolling)
        print(f"rolling refresh: {summary['refreshed']} refreshed "
              f"({summary['priority']} priority-first), {summary['failed']} failed, "
              f"planned {summary['planned']} of {summary['universe']} universe names "
              f"({summary['not_sec_filers']} not SEC filers)")
        # A completely dry run (nothing refreshed, something failed) must alert; a
        # partially failed sweep is tomorrow night's problem, not a dead unit.
        return 1 if (summary["failed"] and not summary["refreshed"]) else 0

    if args.force_refresh:
        if not args.symbols:
            parser.error("--force-refresh needs --symbols")
        wanted = [w.strip().upper() for w in args.symbols.split(",") if w.strip()]
        ciks = cik_map_cached(Path(args.cache), max_age_days=7)
        ok = 0
        for sym in wanted:
            cik = ciks.get(sym)
            if cik is None:
                print(f"{sym}: not in the SEC ticker map — skipped, not guessed")
                continue
            try:
                fetch_companyfacts(cik, cache_dir=Path(args.cache), refresh=True)
                ok += 1
                print(f"{sym}: refreshed")
            except Exception as error:  # noqa: BLE001
                print(f"{sym}: refresh failed ({type(error).__name__}: {error})")
        print(f"force refresh: {ok} of {len(wanted)}")
        return 0 if ok or not wanted else 1

    if not args.sec_data:
        parser.error("--sec-data is required (unless --rolling or --force-refresh)")

    import picks
    import secsv
    meta = picks._load_meta(Path(args.universe))
    prices = picks._load_prices(Path(args.prices) if args.prices else None)
    wanted = ([w.strip().upper() for w in args.symbols.split(",") if w.strip()]
              if args.symbols else None)
    facts = secsv.load_facts(args.sec_data, symbols=wanted)
    secsv.merge_tag_index(facts, args.sec_data, symbols=wanted)
    if wanted:
        for missing in [w for w in wanted if w not in facts]:
            print(f"{missing}: not in the export — skipped, not guessed")
        wanted = [w for w in wanted if w in facts]

    def build(symbol):
        return pit.as_of_bundle(facts[symbol], symbol, meta.get(symbol), args.as_of,
                                prices or {})

    before: dict[str, list[str]] = {}
    targets = []
    for symbol in (wanted or sorted(facts)):
        bundle = build(symbol)
        if bundle is None:
            continue
        missing = gaps(bundle)
        if missing:
            before[symbol] = missing
            targets.append(symbol)
    print(f"{len(targets)} name(s) with registry gaps -> tier 2 ({TIER_EDGAR})")

    added = enrich_payloads(facts, targets, cache_dir=Path(args.cache))
    filled_names = 0
    for symbol in targets:
        if not added.get(symbol):
            continue
        bundle = build(symbol)
        if bundle is None:
            continue
        now_missing = set(gaps(bundle))
        filled = [name for name in before[symbol] if name not in now_missing]
        if filled:
            filled_names += 1
            print(f"{symbol}: filled {', '.join(filled)} "
                  f"(+{len(added[symbol])} tags, {TIER_EDGAR})"
                  + (f"; still n/a: {', '.join(sorted(now_missing))}" if now_missing
                     else ""))
    print(f"tier 2 filled at least one registry metric for {filled_names} of "
          f"{len(targets)} gap name(s)")

    if args.vendor:
        cherry = {}
        for symbol in targets:
            bundle = build(symbol)
            if bundle is None or not gaps(bundle):
                continue
            found = vendor_metrics(symbol)
            if found:
                cherry[symbol] = found
        path = write_vendor(Path(args.cache), cherry)
        print(f"tier 3 (display-only): vendor values for {len(cherry)} name(s) "
              f"-> {path}")

    if args.out:
        rows = [b for b in (build(s) for s in (wanted or sorted(facts))) if b]
        secsv.write_jsonl(rows, args.out)
        print(f"enriched bundles -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
