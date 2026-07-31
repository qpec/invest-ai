"""v3 owner-mode PIT backtest + blinde walk-forward harness (RECONSTRUCTION.md §5.11).

python backtest3.py [--top-n 15] [--calibrate-half A|B] [--cohorts]

Owner-mode (msgs 45-50): buy and sell are different decisions. The simulation drives
formation.py's frozen rule engine — quality ranking, V-percentile entry gate,
persistence quarters, exit-only-on-veto/rank/extreme-duurte — over the same PIT ticks
and scored rows as backtest.py; the constants are formation's own, parameterized ONLY
through the walk-forward grid (a scoped override of formation's module bindings, so
live and backtest share one rule engine bit-identically, msg 44). Position policy:
a new entry is sized at 1/slots of NAV (capped by available cash), held positions are
never resized (hold-until-exit — winners drift), exits and open slots become cash.

Walk-forward (msgs 47/49-50): halves 2021-03..2023-12 and 2024-01..2026-06; grid =
gate percentile {10,20,30} x persistence {1,2,3} x exit rank {30,40} (18 options),
calibrated on one half, blind-tested on the other; pre-registered criterion = beat the
equal-weight pool on the blind half with lower turnover than v2 (the plain top-N
composite policy, backtest.simulate). --cohorts (msg 55): fresh-ranked quality-score
cohorts 1-15/16-50/51-100/101+ per period, no gates, no costs, cumulative per half.
Cores are pure over preloaded {facts, prices, meta} dicts; only main() touches disk.
Outputs reports/backtest3-*.md + .json.
"""
from __future__ import annotations

import argparse
import sys
from contextlib import contextmanager

import backtest
import formation
import pit
import scoring

HALF_A = ("2021-03-01", "2023-12-31")   # §5.11: calibration/blind halves, pinned
HALF_B = ("2024-01-01", "2026-06-30")
GRID = [{"gate_pctl": g, "persistence": p, "exit_rank": x}
        for g in (10.0, 20.0, 30.0) for p in (1, 2, 3) for x in (30, 40)]
COHORT_BUCKETS = (("1-15", 1, 15), ("16-50", 16, 50),
                  ("51-100", 51, 100), ("101+", 101, None))
STATS_KEYS = ("final_nav", "annualized_pct", "max_drawdown_pct", "avg_turnover_pct")


@contextmanager
def formation_params(*, slots: int, gate_pctl: float, persistence: int, exit_rank: int):
    """Scoped override of formation.py's frozen §4.7 bindings (SLOTS/GATE_V_PCTL/
    PERSISTENCE_QUARTERS/EXIT_RANK; EXIT_V_PCTL is never varied) — the ONLY sanctioned
    parameterization path (§5.11), always restored, so the live rule engine itself
    stays untouched."""
    saved = (formation.SLOTS, formation.GATE_V_PCTL,
             formation.PERSISTENCE_QUARTERS, formation.EXIT_RANK)
    formation.SLOTS, formation.GATE_V_PCTL = slots, gate_pctl
    formation.PERSISTENCE_QUARTERS, formation.EXIT_RANK = persistence, exit_rank
    try:
        yield
    finally:
        (formation.SLOTS, formation.GATE_V_PCTL,
         formation.PERSISTENCE_QUARTERS, formation.EXIT_RANK) = saved


# ------------------------------------------------------- owner-mode simulation core

def simulate_owner(scored_by_tick: dict, prices: dict, ticks: list[str], *,
                   top_n: int = scoring.SLOTS,
                   gate_pctl: float = scoring.GATE_V_PCTL,
                   persistence: int = scoring.PERSISTENCE_QUARTERS,
                   exit_rank: int = scoring.EXIT_RANK,
                   cost_bp: float = backtest.DEFAULT_COST_BP) -> dict:
    """§5.11 owner-mode loop: per tick formation.update over the alive+priced scored
    rows (quarterly grid, so streaks advance every tick, msg 62), then the position
    policy (entries 1/slots, holds drift, exits/open slots -> cash); a delisted squad
    member is force-exited at its last price (formation itself never sells on absence
    of evidence). NAV/cost conventions match backtest.simulate: nav[ticks[0]] = 1.0
    pre-cost, terminal tick logs but never rebalances, turnover = sum |w_new - w_old|."""
    cost_rate = cost_bp / 10000.0
    with formation_params(slots=top_n, gate_pctl=gate_pctl,
                          persistence=persistence, exit_rank=exit_rank):
        state, nav, weights = None, 1.0, {}
        nav_track = {ticks[0]: 1.0}
        turnovers, holdings_log = [], []
        for i, tick in enumerate(ticks):
            if i == len(ticks) - 1:
                holdings_log.append({"date": tick, "held": sorted(weights),
                                     "transfers": []})
                break
            rows = [r for r in scored_by_tick[tick]
                    if backtest.alive(prices, r["symbol"], tick)
                    and pit.price_at(prices, r["symbol"], tick, "close") is not None]
            state, transfers = formation.update(state, rows, tick)
            dead = [m["symbol"] for m in state["squad"]
                    if not backtest.alive(prices, m["symbol"], tick)]
            if dead:
                exits = [{"date": tick, "action": "out", "symbol": s,
                          "reason": "eruit — delist: koersreeks eindigt, "
                                    "exit tegen laatste koers"} for s in dead]
                state["squad"] = [m for m in state["squad"]
                                  if m["symbol"] not in set(dead)]
                state["transfers"] += exits
                transfers = transfers + exits
            squad = {m["symbol"] for m in state["squad"]}
            old = weights
            weights = {s: w for s, w in old.items() if s in squad}
            cash = 1.0 - sum(weights.values())
            entries = sorted(squad - set(weights))
            if entries and cash > 0:
                per = min(1.0 / top_n, cash / len(entries))
                for s in entries:
                    weights[s] = per
            turnover = sum(abs(weights.get(s, 0.0) - old.get(s, 0.0))
                           for s in set(weights) | set(old))
            turnovers.append(turnover)
            nav *= 1.0 - cost_rate * turnover
            holdings_log.append({"date": tick, "held": sorted(weights),
                                 "transfers": transfers})
            t1 = ticks[i + 1]
            rets = {}
            for s in weights:
                r = backtest.fwd_return(prices, s, tick, t1)
                rets[s] = 0.0 if r is None else r
            factor = 1.0 + sum(w * rets[s] for s, w in weights.items())
            nav = max(nav * factor, 0.0)
            weights = ({s: w * (1.0 + rets[s]) / factor for s, w in weights.items()}
                       if factor > 0 else {})
            nav_track[t1] = nav
    return {"nav": nav_track, "final_nav": nav,
            "annualized_pct": backtest.annualized_pct(nav_track),
            "max_drawdown_pct": backtest.max_drawdown_pct(nav_track),
            "turnover_pct": [100.0 * t for t in turnovers],
            "avg_turnover_pct": backtest.avg_turnover_pct(turnovers),
            "holdings_log": holdings_log, "state": state}


# ------------------------------------------------------- walk-forward harness (§5.11)

def _stats(track: dict) -> dict:
    return {k: track.get(k) for k in STATS_KEYS}


def _beats(a: dict, b: dict) -> bool:
    """a's annualized return strictly beats b's (either missing -> no claim)."""
    return (a["annualized_pct"] is not None and b["annualized_pct"] is not None
            and a["annualized_pct"] > b["annualized_pct"])


def _lower_turnover(a: dict, b: dict) -> bool:
    return (a["avg_turnover_pct"] is not None and b["avg_turnover_pct"] is not None
            and a["avg_turnover_pct"] < b["avg_turnover_pct"])


def _criterion(v3: dict, v2: dict, pool: dict) -> dict:
    """The pre-registered §5.11 criterion (msg 47): beat the equal-weight pool, with
    lower turnover than v2 (the plain rotation policy)."""
    beats_pool, lower = _beats(v3, pool), _lower_turnover(v3, v2)
    return {"beats_pool": beats_pool, "lower_turnover_than_v2": lower,
            "met": beats_pool and lower}


def half_ticks(ticks: list[str]) -> dict[str, list[str]]:
    """The full tick grid partitioned into the pinned §5.11 halves."""
    return {"A": [t for t in ticks if HALF_A[0] <= t <= HALF_A[1]],
            "B": [t for t in ticks if HALF_B[0] <= t <= HALF_B[1]]}


def walk_forward(scored_by_tick: dict, prices: dict, ticks: list[str], *,
                 top_n: int = scoring.SLOTS,
                 cost_bp: float = backtest.DEFAULT_COST_BP,
                 calibrate_halves: tuple[str, ...] = ("A", "B")) -> dict:
    """§5.11 harness (pure): per direction, run the 18-option grid on the calibration
    half, pick the winner (criterion met first, then annualized return, then the
    smallest combo — deterministic), evaluate it blind on the other half against
    v2 / pool / SPY, and report the pre-registered verdict. Both directions by
    default (msg 47 'en andersom')."""
    halves = half_ticks(ticks)
    directions = []
    for cal in calibrate_halves:
        blind = "B" if cal == "A" else "A"
        cal_t, blind_t = halves[cal], halves[blind]
        if len(cal_t) < 2 or len(blind_t) < 2:
            raise ValueError(f"half {cal if len(cal_t) < 2 else blind} has fewer "
                             f"than 2 ticks — nothing to calibrate/test on")
        v2_cal = backtest.simulate(scored_by_tick, prices, cal_t,
                                   top_n=top_n, cost_bp=cost_bp)
        pool_cal = backtest.simulate(scored_by_tick, prices, cal_t,
                                     top_n=None, cost_bp=0.0)
        grid = []
        for combo in GRID:
            v3_cal = simulate_owner(scored_by_tick, prices, cal_t, top_n=top_n,
                                    cost_bp=cost_bp, **combo)
            grid.append({**combo, **_stats(v3_cal),
                         "meets_criterion": _criterion(v3_cal, v2_cal, pool_cal)["met"]})
        chosen = min(grid, key=lambda g: (
            not g["meets_criterion"],
            -(g["annualized_pct"] if g["annualized_pct"] is not None else -1e9),
            g["gate_pctl"], g["persistence"], g["exit_rank"]))
        combo = {k: chosen[k] for k in ("gate_pctl", "persistence", "exit_rank")}
        v3 = simulate_owner(scored_by_tick, prices, blind_t, top_n=top_n,
                            cost_bp=cost_bp, **combo)
        v2 = backtest.simulate(scored_by_tick, prices, blind_t,
                               top_n=top_n, cost_bp=cost_bp)
        pool = backtest.simulate(scored_by_tick, prices, blind_t,
                                 top_n=None, cost_bp=0.0)
        spy_nav = backtest.spy_track(prices, blind_t)
        directions.append({
            "calibrate_half": cal, "blind_half": blind, "grid": grid, "chosen": combo,
            "blind": {"v3": {**_stats(v3), "holdings_log": v3["holdings_log"]},
                      "v2": _stats(v2), "pool": _stats(pool),
                      "spy": {"annualized_pct": backtest.annualized_pct(spy_nav),
                              "max_drawdown_pct": backtest.max_drawdown_pct(spy_nav)}},
            "criterion": _criterion(v3, v2, pool)})
    return {"top_n": top_n, "cost_bp": cost_bp,
            "halves": {h: {"ticks": t} for h, t in halves.items()},
            "directions": directions,
            "degraded_price_symbols": backtest.degraded_price_symbols(prices),
            "disclosures": backtest.disclosures(
                cost_bp, backtest.degraded_price_symbols(prices)) + [
                "Owner-mode posities: instap 1/slots van NAV (begrensd door beschikbare "
                "cash), zittende posities driften onaangeroerd tot een exit; open "
                "plekken en exits blijven cash; pool- en SPY-tracks frictieloos.",
                "Parameters lopen uitsluitend via het walk-forward-grid over "
                "formation.py's bevroren regelmotor; EXIT_V_PCTL wordt nooit gevarieerd."]}


# ------------------------------------------------------- quality cohorts (msg 55)

def quality_cohorts(scored_by_tick: dict, prices: dict, ticks: list[str]) -> dict:
    """§5.11 --cohorts (pure): each period, rank alive+priced names fresh on
    quality_score (no gates, no persistence, no costs), equal-weight the rank buckets
    1-15/16-50/51-100/101+, and compound per half + whole. A period where a bucket is
    empty contributes factor 1 (cash). Returns cumulative % per bucket per period."""
    growth = {label: {"A": 1.0, "B": 1.0, "whole": 1.0} for label, _, _ in COHORT_BUCKETS}
    periods = {label: {"A": 0, "B": 0, "whole": 0} for label, _, _ in COHORT_BUCKETS}
    for t0, t1 in zip(ticks, ticks[1:]):
        ranked = sorted(
            (r for r in scored_by_tick[t0]
             if r.get("quality_score") is not None
             and backtest.alive(prices, r["symbol"], t0)
             and pit.price_at(prices, r["symbol"], t0, "close") is not None),
            key=lambda r: (-r["quality_score"], r["symbol"]))
        half = "A" if t0 <= HALF_A[1] else "B"
        for label, lo, hi in COHORT_BUCKETS:
            members = ranked[lo - 1: hi]
            rets = [r for m in members
                    if (r := backtest.fwd_return(prices, m["symbol"], t0, t1)) is not None]
            if not rets:
                continue
            factor = 1.0 + sum(rets) / len(rets)
            for scope in (half, "whole"):
                growth[label][scope] *= factor
                periods[label][scope] += 1
    return {"buckets": {
        label: {scope: (100.0 * (growth[label][scope] - 1.0)
                        if periods[label][scope] else None)
                for scope in ("A", "B", "whole")} for label, _, _ in COHORT_BUCKETS},
        "periods": periods}


# --------------------------------------------------------------------- reports

_PERIOD_LABELS = (("A", f"{HALF_A[0][:4]}→{HALF_A[1][:4]}"),
                  ("B", f"{HALF_B[0][:4]}→{HALF_B[1][:4]}"),
                  ("whole", "Hele periode"))


def render_walkforward_report(result: dict) -> str:
    """§5.11 walk-forward md (pure): per direction the chosen combo, the blind-half
    v3/v2/pool/SPY table (msg 50 shape), the pre-registered verdict, and the
    in-sample grid."""
    lines = [f"# v3 owner-mode — blinde walk-forward (top-{result['top_n']}, "
             f"kosten {result['cost_bp']:g} bp)", "",
             f"Helft A = {HALF_A[0]} → {HALF_A[1]} "
             f"({len(result['halves']['A']['ticks'])} ticks) · "
             f"Helft B = {HALF_B[0]} → {HALF_B[1]} "
             f"({len(result['halves']['B']['ticks'])} ticks) · grid {len(GRID)} opties"]
    for d in result["directions"]:
        c = d["chosen"]
        lines += ["", f"## Kalibratie {d['calibrate_half']} → blinde test "
                      f"{d['blind_half']}", "",
                  f"Gekozen uit {len(d['grid'])} opties: poort V ≥ "
                  f"{c['gate_pctl']:g}e percentiel · {c['persistence']} kwartaal/"
                  f"kwartalen bewijs · verkoopgrens rang {c['exit_rank']}", "",
                  f"| Blinde helft {d['blind_half']} | %/jr | max drawdown "
                  f"| omzet/kwartaal |",
                  "|---|------|--------------|----------------|"]
        for label, key in (("v3 owner-mode", "v3"), ("v2 (top-N composite)", "v2"),
                           ("Equal-weight pool", "pool"), ("SPY", "spy")):
            t = d["blind"][key]
            lines.append(f"| {label} | {backtest.pct(t['annualized_pct'])} "
                         f"| {backtest.pct(t['max_drawdown_pct'])} "
                         f"| {backtest.pct(t.get('avg_turnover_pct'), '.1f')} |")
        v = d["criterion"]
        lines += ["", "Pre-geregistreerd criterium — pool verslaan op de blinde helft "
                      "met minder omzet dan v2: "
                      f"{'✅ gehaald' if v['met'] else '❌ niet gehaald'} "
                      f"(pool verslagen: {'ja' if v['beats_pool'] else 'nee'} · "
                      f"omzet lager dan v2: "
                      f"{'ja' if v['lower_turnover_than_v2'] else 'nee'})", "",
                  "### Kalibratie-grid (in-sample)", "",
                  "| poort | bewijs | verkooprang | %/jr | omzet/kw | criterium |",
                  "|-------|--------|-------------|------|----------|-----------|"]
        for g in d["grid"]:
            lines.append(f"| {g['gate_pctl']:g} | {g['persistence']} "
                         f"| {g['exit_rank']} | {backtest.pct(g['annualized_pct'])} "
                         f"| {backtest.pct(g['avg_turnover_pct'], '.1f')} "
                         f"| {'✓' if g['meets_criterion'] else '—'} |")
    lines += ["", "## Disclosures", ""]
    lines += [f"- {d}" for d in result["disclosures"]]
    lines += ["", "---",
              "*Regels afgesteld op de éne helft, blind getest op de ándere — wie op "
              "de testjaren tunet, wint alleen op papier.*", ""]
    return "\n".join(lines)


def render_cohorts_report(result: dict) -> str:
    """The msg 55 table (pure): cumulative quality-cohort returns per half + whole."""
    labels = [label for label, _, _ in COHORT_BUCKETS]
    lines = ["# Kwaliteits-cohorten — vers gerangschikt, zonder poorten (msg 55)", "",
             "Elk kwartaal opnieuw gerangschikt op kwaliteitsscore (motor B), "
             "gelijkgewogen per cohort, geen poorten, geen kosten.", "",
             "| Periode | " + " | ".join(f"Rang {label}" for label in labels) + " |",
             "|---------|" + "|".join("------" for _ in labels) + "|"]
    for scope, name in _PERIOD_LABELS:
        cells = [backtest.pct(result["buckets"][label][scope], "+.0f")
                 for label in labels]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "De kale kwaliteits-rangschikking is de nulmeting: de alpha van v3 "
                  "zit in de poorten en het eigenaarsgedrag eromheen, niet in de "
                  "lijst zelf (msg 55).", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="v3 owner-mode backtest + walk-forward harness (spec §5.11)")
    ap.add_argument("--top-n", type=int, default=scoring.SLOTS)
    ap.add_argument("--calibrate-half", choices=("A", "B"), default=None,
                    help="calibrate on one half only (default: both directions)")
    ap.add_argument("--cohorts", action="store_true",
                    help="fresh-ranked quality cohorts instead of the walk-forward")
    ap.add_argument("--cost-bp", type=float, default=backtest.DEFAULT_COST_BP)
    ap.add_argument("--bt-cache", default=str(backtest.BT_DIR))
    ap.add_argument("--universe", default="universe.csv")
    args = ap.parse_args(argv)

    facts, prices, meta = backtest.load_bt_cache(args.bt_cache, args.universe)
    if not facts or "SPY" not in prices:
        print("bt_cache is leeg of mist SPY — draai eerst bt_fetch.py", file=sys.stderr)
        return 1
    legacy = backtest.degraded_price_symbols(prices)
    if legacy:
        print(f"LET OP: {len(legacy)} koersroosters zonder ruwe close — "
              f"marktkapitalisatie draagt latere splits/dividenden; draai bt_fetch.py "
              f"opnieuw (staat ook in de disclosures).", file=sys.stderr)
    ticks = pit.quarter_ends(prices["SPY"], HALF_A[0], HALF_B[1])
    if len(ticks) < 2:
        print("minder dan 2 ticks op het SPY-grid — te weinig prijshistorie",
              file=sys.stderr)
        return 1
    scored_by_tick = backtest.score_ticks(facts, prices, meta, ticks)
    span = f"{HALF_A[0]}-{HALF_B[1]}"

    if args.cohorts:
        result = quality_cohorts(scored_by_tick, prices, ticks)
        md_path, json_path = backtest.write_reports(
            result, render_cohorts_report(result), f"backtest3-cohorts-{span}")
    else:
        halves = ("A", "B") if args.calibrate_half is None else (args.calibrate_half,)
        result = walk_forward(scored_by_tick, prices, ticks, top_n=args.top_n,
                              cost_bp=args.cost_bp, calibrate_halves=halves)
        for d in result["directions"]:
            v = d["criterion"]
            print(f"kalibratie {d['calibrate_half']} → blind {d['blind_half']}: "
                  f"v3 {backtest.pct(d['blind']['v3']['annualized_pct'])}/jr · "
                  f"pool {backtest.pct(d['blind']['pool']['annualized_pct'])}/jr · "
                  f"criterium {'✅' if v['met'] else '❌'}")
        md_path, json_path = backtest.write_reports(
            result, render_walkforward_report(result), f"backtest3-{span}")
    print(f"-> {md_path}\n-> {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
