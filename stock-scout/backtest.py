"""v2-composite PIT backtest: quarterly top-N over the EDGAR bt_cache (RECONSTRUCTION.md §5.10).

python backtest.py [--start 2021-03-01] [--end today] [--top-n 15] [--cost-bp 10]

The backtest half of the decoupling seam (§1 msg 44): every rebalance tick — the last
weekly SPY bar per calendar quarter, pit.quarter_ends — builds PIT bundles for every
symbol in bt_cache/facts and feeds them to scoring.score_universe, literally the same
pure code as the live run. Portfolio = top-N by composite, equal-weight; cost_bp charged
on turnover (sum |w_new - w_old|); a delisted name (price series ends) exits at its last
available price and is never re-selected. Tracks strategy / SPY / equal-weight-pool NAV,
per-band forward-quarter cohorts (A/B/C/D/F/VETOED — the msg 44 table shape) and a tick
log (top-5 + pool size). The simulation core is pure over preloaded {facts, prices, meta}
dicts (tests inject synthetic data); only load_bt_cache/main touch disk. Outputs
reports/backtest-<start>-<end>.md + .json with the §5.10 disclosure set.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

import pit
import scoring

BANDS = ("A", "B", "C", "D", "F", "VETOED")
DEFAULT_COST_BP = 10.0
BT_DIR = Path("bt_cache")
REPORTS_DIR = Path("reports")


def disclosures(cost_bp: float, degraded: list[str] | None = None) -> list[str]:
    """The §5.10 disclosure set (msg 44): PIT discipline, survivorship both directions,
    cost model, data caveats — printed in full under every report. `degraded` names the
    symbols whose price grid still lacks raw closes (legacy §3.6 files), which adds the
    split-contamination caveat to the set."""
    extra = []
    if degraded:
        extra.append(
            f"Koersdata-degradatie: {len(degraded)} symbolen "
            f"({', '.join(sorted(degraded)[:8])}"
            f"{', ...' if len(degraded) > 8 else ''}) hebben nog een oud koersrooster "
            "zonder ruwe close; hun marktkapitalisatie is met een aangepaste "
            "(split/dividend-gecorrigeerde) koers gebouwd en draagt dus latere "
            "corporate actions in zich — draai bt_fetch.py opnieuw om ze te verversen.")
    return extra + [
        "PIT-discipline: alleen EDGAR-facts met filed-datum <= de tick zijn zichtbaar; "
        "per periode geldt de laatst-gefilede waarde (restatements zoals toen bekend) — "
        "lookahead is onmogelijk gemaakt, niet slechts vermeden.",
        "Survivorship, beide richtingen: het universum is de huidige lijst — verdwenen "
        "namen (delistings, faillissementen) ontbreken, wat vooral het VETOED-cohort "
        "flatteert (dode cash-burners staan er niet meer in); later genoteerde namen "
        "doen pas mee zodra hun filings verschijnen, dus de pool groeit door de tijd.",
        f"Kostenmodel: {cost_bp:g} bp op omzet (som |w_nieuw - w_oud| per herweging, "
        "initiële aankoop inbegrepen); de SPY- en pool-tracks zijn frictieloos; geen "
        "slippage, belastingen of valuta-effecten.",
        "Data-kanttekeningen: fundamentals uitsluitend uit EDGAR (niet-EDGAR-noteringen "
        "zoals de .AS-namen ontbreken); weekkoersen, geen intraday; delisting = exit "
        "tegen de laatste beschikbare koers; marktkapitalisatie = dei-aandelen x de RUWE "
        "weekslotkoers (nooit de aangepaste — die wordt door latere splits/dividenden "
        "herschaald en zou de toekomst in elke historische tick smokkelen), terwijl "
        "rendement/NAV juist op de aangepaste koers loopt (totaalrendement); geen "
        "Yahoo-EV in de PIT-wereld (EV_GAP vuurt nooit).",
    ]


def degraded_price_symbols(prices: dict) -> list[str]:
    """Symbols whose §3.6 grid is still legacy (plain floats, no raw close of its own) —
    their PIT market caps carry later splits/dividends. Fed to disclosures()."""
    return sorted(sym for sym, grid in prices.items() if pit.grid_is_degraded(grid))


# ---------------------------------------------------------------- pure price helpers

def alive(prices: dict, symbol: str, tick: str) -> bool:
    """§5.10 delist test: a name is alive at a tick while its price series still runs
    (last bar at or after the tick); a series that ended before the tick is delisted."""
    grid = prices.get(symbol) or {}
    return bool(grid) and max(grid) >= tick


def fwd_return(prices: dict, symbol: str, t0: str, t1: str) -> float | None:
    """Forward TOTAL return t0 -> t1 from the §3.6 weekly grid, on adj_close: dividends
    count and a split in between is not a -50% crash (the raw close belongs to market-cap
    math only). price_at is last-bar-at-or-before, so a mid-quarter delisting naturally
    exits at its last available price."""
    p0 = pit.price_at(prices, symbol, t0, "adj_close")
    p1 = pit.price_at(prices, symbol, t1, "adj_close")
    if p0 is None or p1 is None or p0 <= 0:
        return None
    return p1 / p0 - 1.0


# ------------------------------------------------------------------- NAV statistics

def annualized_pct(nav: dict) -> float | None:
    """Annualized return %/yr over a {tick: nav} track (calendar-day exponent)."""
    if len(nav) < 2:
        return None
    d0, d1 = min(nav), max(nav)
    days = (date.fromisoformat(d1) - date.fromisoformat(d0)).days
    if days <= 0 or nav[d0] <= 0 or nav[d1] <= 0:
        return None
    return 100.0 * ((nav[d1] / nav[d0]) ** (365.25 / days) - 1.0)


def max_drawdown_pct(nav: dict) -> float | None:
    """Worst peak-to-trough % over a {tick: nav} track (tick granularity)."""
    if not nav:
        return None
    peak, worst = 0.0, 0.0
    for day in sorted(nav):
        peak = max(peak, nav[day])
        if peak > 0:
            worst = min(worst, nav[day] / peak - 1.0)
    return 100.0 * worst


def avg_turnover_pct(turnovers: list[float]) -> float | None:
    """Mean per-rebalance turnover in %, the initial buy-in excluded (it is always
    ~100% and would drown the steady-state figure the msg 50 comparison uses)."""
    steady = turnovers[1:] if len(turnovers) > 1 else turnovers
    return 100.0 * sum(steady) / len(steady) if steady else None


# ------------------------------------------------------------- tick scoring (§5.10)

def score_ticks(facts: dict, prices: dict, meta: dict, ticks: list[str]) -> dict:
    """Per tick: PIT bundles for every symbol with facts -> scoring.score_universe
    (the shared decision layer, §4). Returns {tick: §3.3 scored rows}."""
    out = {}
    for tick in ticks:
        bundles = []
        for symbol in sorted(facts):
            bundle = pit.as_of_bundle(facts[symbol], symbol, meta.get(symbol), tick, prices)
            if bundle is not None:
                bundles.append(bundle)
        out[tick] = scoring.score_universe(bundles)
    return out


def candidates_at(scored: list[dict], prices: dict, tick: str) -> list[dict]:
    """The tick's pool: graded rows (composite present) that are alive and priced (the raw
    close — the one the PIT market cap was built on), sorted by (-composite, symbol).
    VETOED/INSUFFICIENT never rank (§4.6)."""
    rows = [r for r in scored
            if r.get("composite") is not None and alive(prices, r["symbol"], tick)
            and pit.price_at(prices, r["symbol"], tick, "close") is not None]
    rows.sort(key=lambda r: (-r["composite"], r["symbol"]))
    return rows


# ---------------------------------------------------------- the v2 simulation core

def simulate(scored_by_tick: dict, prices: dict, ticks: list[str], *,
             top_n: int | None, cost_bp: float) -> dict:
    """§5.10 quarterly rebalance loop (pure). Each tick: pool -> top-N by composite
    (top_n=None: the whole pool, the equal-weight benchmark) -> equal-weight target;
    cost = turnover x cost_bp; hold to the next tick on the weekly grid (delistings
    exit at last price); weights drift between rebalances. nav[ticks[0]] = 1.0
    pre-cost — a tick's rebalance cost lands in the next recorded value; the terminal
    tick logs holdings but is never rebalanced (no forward period to pay for)."""
    cost_rate = cost_bp / 10000.0
    nav, weights = 1.0, {}
    nav_track = {ticks[0]: 1.0}
    turnovers, tick_log = [], []
    for i, tick in enumerate(ticks):
        pool = candidates_at(scored_by_tick[tick], prices, tick)
        top = pool if top_n is None else pool[:top_n]
        if i == len(ticks) - 1:
            tick_log.append({"date": tick, "pool": len(pool),
                             "top5": [r["symbol"] for r in pool[:5]],
                             "held": sorted(weights)})
            break
        target = {r["symbol"]: 1.0 / len(top) for r in top} if top else {}
        turnover = sum(abs(target.get(s, 0.0) - weights.get(s, 0.0))
                       for s in set(target) | set(weights))
        turnovers.append(turnover)
        nav *= 1.0 - cost_rate * turnover
        tick_log.append({"date": tick, "pool": len(pool),
                         "top5": [r["symbol"] for r in pool[:5]],
                         "held": sorted(target)})
        t1 = ticks[i + 1]
        rets = {}
        for s in target:
            r = fwd_return(prices, s, tick, t1)
            rets[s] = 0.0 if r is None else r
        factor = 1.0 + sum(w * rets[s] for s, w in target.items())
        nav = max(nav * factor, 0.0)
        weights = ({s: target[s] * (1.0 + rets[s]) / factor for s in target}
                   if factor > 0 else {})
        nav_track[t1] = nav
    return {"nav": nav_track, "final_nav": nav,
            "annualized_pct": annualized_pct(nav_track),
            "max_drawdown_pct": max_drawdown_pct(nav_track),
            "turnover_pct": [100.0 * t for t in turnovers],
            "avg_turnover_pct": avg_turnover_pct(turnovers),
            "tick_log": tick_log}


def spy_track(prices: dict, ticks: list[str]) -> dict:
    """SPY NAV normalized to 1.0 at the first tick (the §5.10 benchmark track) — total
    return, so adj_close like every other NAV track."""
    base = pit.price_at(prices, "SPY", ticks[0], "adj_close")
    if base is None or base <= 0:
        return {}
    track = {}
    for tick in ticks:
        px = pit.price_at(prices, "SPY", tick, "adj_close")
        if px is not None:
            track[tick] = px / base
    return track


def band_cohorts(scored_by_tick: dict, prices: dict, ticks: list[str]) -> dict:
    """§5.10 validation cohorts: per band A/B/C/D/F/VETOED the forward-quarter returns
    of every name-quarter (name alive+priced at the tick; delistings count their exit
    return, msg 44). INSUFFICIENT rows carry no signal claim and are excluded."""
    returns = {band: [] for band in BANDS}
    for t0, t1 in zip(ticks, ticks[1:]):
        for row in scored_by_tick[t0]:
            if row["grade"] not in returns or not alive(prices, row["symbol"], t0):
                continue
            fwd = fwd_return(prices, row["symbol"], t0, t1)
            if fwd is not None:
                returns[row["grade"]].append(fwd)
    return {band: {"name_quarters": len(vals),
                   "mean_quarter_return_pct":
                       100.0 * sum(vals) / len(vals) if vals else None}
            for band, vals in returns.items()}


def run_backtest(facts: dict, prices: dict, meta: dict, *, start: str, end: str,
                 top_n: int = 15, cost_bp: float = DEFAULT_COST_BP) -> dict:
    """The pure §5.10 end-to-end core over preloaded dicts: SPY quarter grid ->
    score_ticks -> strategy/pool/SPY tracks + band cohorts + tick log + disclosures."""
    ticks = pit.quarter_ends(prices.get("SPY") or {}, start, end)
    if len(ticks) < 2:
        raise ValueError("fewer than 2 rebalance ticks on the SPY grid for this range")
    scored_by_tick = score_ticks(facts, prices, meta, ticks)
    strategy = simulate(scored_by_tick, prices, ticks, top_n=top_n, cost_bp=cost_bp)
    pool = simulate(scored_by_tick, prices, ticks, top_n=None, cost_bp=0.0)
    pool.pop("tick_log")
    spy_nav = spy_track(prices, ticks)
    return {"start": start, "end": end, "ticks": ticks, "quarters": len(ticks) - 1,
            "top_n": top_n, "cost_bp": cost_bp,
            "strategy": {k: v for k, v in strategy.items() if k != "tick_log"},
            "pool": pool,
            "spy": {"nav": spy_nav, "annualized_pct": annualized_pct(spy_nav),
                    "max_drawdown_pct": max_drawdown_pct(spy_nav)},
            "bands": band_cohorts(scored_by_tick, prices, ticks),
            "tick_log": strategy["tick_log"],
            "degraded_price_symbols": degraded_price_symbols(prices),
            "disclosures": disclosures(cost_bp, degraded_price_symbols(prices))}


# ------------------------------------------------------------------- report (§5.10)

def pct(x, spec: str = "+.1f") -> str:
    return "—" if x is None else f"{x:{spec}}%"


def render_report(result: dict) -> str:
    """The §5.10 report md (pure): track table, msg 44 band table, tick log, disclosures."""
    lines = [
        f"# PIT-backtest {result['start']} → {result['end']} "
        f"(v2 composite top-{result['top_n']})", "",
        f"{result['quarters']} kwartalen · rebalance-grid = laatste SPY-weekbar per "
        f"kalenderkwartaal · kosten {result['cost_bp']:g} bp op omzet", "",
        "| Track | eind-NAV | %/jr | max drawdown | omzet/kwartaal |",
        "|-------|----------|------|--------------|----------------|",
    ]
    for label, track in ((f"Scout top-{result['top_n']}", result["strategy"]),
                         ("Equal-weight pool", result["pool"]),
                         ("SPY", result["spy"])):
        nav_end = track["nav"][max(track["nav"])] if track.get("nav") else None
        lines.append(
            f"| {label} | {'—' if nav_end is None else f'{nav_end:.3f}'} "
            f"| {pct(track['annualized_pct'])} | {pct(track['max_drawdown_pct'])} "
            f"| {pct(track.get('avg_turnover_pct'), '.1f')} |")
    lines += ["", "## Band-cohorten (forward-kwartaalrendement)", "",
              "| Band | naam-kwartalen | gem. kwartaalrendement |",
              "|------|----------------|------------------------|"]
    for band in BANDS:
        cohort = result["bands"][band]
        lines.append(f"| {band} | {cohort['name_quarters']} "
                     f"| {pct(cohort['mean_quarter_return_pct'], '+.2f')} |")
    lines += ["", "## Tick-log", "", "| datum | pool | top-5 |", "|-------|------|-------|"]
    for entry in result["tick_log"]:
        lines.append(f"| {entry['date']} | {entry['pool']} "
                     f"| {', '.join(entry['top5']) or '—'} |")
    lines += ["", "## Disclosures", ""]
    lines += [f"- {d}" for d in result["disclosures"]]
    lines += ["", "---",
              "*Een backtest is bewijsvoering over het verleden, geen belofte — het "
              "model adviseert en monitort, het handelt nooit.*", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------- I/O + CLI

def load_bt_cache(bt_dir: str | Path = BT_DIR,
                  universe_path: str | Path = "universe.csv") -> tuple[dict, dict, dict]:
    """bt_cache/ + universe.csv -> ({symbol: facts}, {symbol: price grid incl. SPY},
    {symbol: meta}) for the pure cores (§3.6, §5.10).

    Every dict is keyed by the TRUE universe symbol, never by the filename stem: the
    writer sanitizes '/' to '-' (BRK/B -> BRK-B.json), so a stem key would miss its meta
    row (no sector -> wrong tier, wrong sector cohort) and mismatch the universe symbol
    everywhere downstream. The symbol is read from inside the payload, with the universe's
    own sanitized-name map as the fallback for files written before that annotation."""
    bt_dir = Path(bt_dir)
    meta, by_stem = {}, {}
    universe_path = Path(universe_path)
    if universe_path.exists():
        for row in pd.read_csv(universe_path).to_dict("records"):
            symbol = str(row["symbol"])
            meta[symbol] = {"name": row.get("name"), "sector": row.get("sector"),
                            "industry": row.get("industry")}
            by_stem[pit.cache_stem(symbol)] = symbol

    facts, prices = {}, {}
    for path in sorted((bt_dir / "facts").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        facts[pit.facts_symbol(payload) or by_stem.get(path.stem) or path.stem] = payload
    for path in sorted((bt_dir / "prices").glob("*.json")):
        symbol, grid = pit.load_price_file(json.loads(path.read_text(encoding="utf-8")))
        prices[symbol or by_stem.get(path.stem) or path.stem] = grid
    return facts, prices, meta


def write_reports(result: dict, md: str, stem: str,
                  reports_dir: str | Path = REPORTS_DIR) -> tuple[Path, Path]:
    """result + rendered md -> reports/<stem>.md + .json (§5.10 output contract)."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / f"{stem}.md"
    json_path = reports_dir / f"{stem}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False,
                                    allow_nan=False), encoding="utf-8")
    return md_path, json_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="v2-composite PIT backtest (spec §5.10)")
    ap.add_argument("--start", default="2021-03-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--top-n", type=int, default=15)
    ap.add_argument("--cost-bp", type=float, default=DEFAULT_COST_BP)
    ap.add_argument("--bt-cache", default=str(BT_DIR), help="bt_cache directory (§3.6)")
    ap.add_argument("--universe", default="universe.csv")
    args = ap.parse_args(argv)

    facts, prices, meta = load_bt_cache(args.bt_cache, args.universe)
    if not facts or "SPY" not in prices:
        print("bt_cache is leeg of mist SPY — draai eerst bt_fetch.py", file=sys.stderr)
        return 1
    legacy = degraded_price_symbols(prices)
    if legacy:
        print(f"LET OP: {len(legacy)} koersroosters zonder ruwe close — marktkapitalisatie "
              f"draagt latere splits/dividenden; draai bt_fetch.py opnieuw. "
              f"(staat ook in de disclosures)", file=sys.stderr)
    result = run_backtest(facts, prices, meta, start=args.start, end=args.end,
                          top_n=args.top_n, cost_bp=args.cost_bp)
    md_path, json_path = write_reports(result, render_report(result),
                                       f"backtest-{args.start}-{args.end}")
    s, p, b = result["strategy"], result["pool"], result["spy"]
    print(f"{result['quarters']} kwartalen · strategie {pct(s['annualized_pct'])}/jr "
          f"· pool {pct(p['annualized_pct'])}/jr · SPY {pct(b['annualized_pct'])}/jr")
    print(f"-> {md_path}\n-> {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
