"""Frozen v3 owner-mode formation rules + formation-state.json (spec §4.7, §5.6, §3.4;
chat msgs 57-58, 62).

Buy and sell are different decisions. The quality engine ranks graded names by
scoring.quality_score (B = 0.40·Q + 0.25·G + 0.20·D + 0.15·M — price excluded); the
price gate is the V pillar score (already the sector percentile of owner-FCF yield).
Entry pool = quality rank <= SLOTS AND V-percentile >= GATE_V_PCTL; a name must sit
in the pool PERSISTENCE_QUARTERS consecutive quarters before it enters the squad
(msg 50: "twee kwartalen bewijs"). Exit ONLY on veto / quality rank > EXIT_RANK /
V-percentile < EXIT_V_PCTL (extreme duurte) — winners and sitting players get rest
(msg 58: DOCU at rank 35 stays). Every constant is imported from scoring.py, never
redefined here.

The bench is the waiting room around the entry pool: gate-passing names ranked
anywhere inside the candidate band (rank <= BENCH_RANK, the same rank at which a
seated name would be sold) that are not seated. They collect a quarter of evidence
per quarter; a bench member is promoted when it has BOTH the persistence
(streak >= PERSISTENCE_QUARTERS) AND a spot in the entry pool (rank <= SLOTS,
through the price gate) AND an open slot — msg 58's first formation, 14 seated with
KRYS/CPAY/GDDY/FTNT/NVDA "waiting one more quarter for their evidence".

Quarter discipline (msg 62 fix): the quarter key is the calendar quarter of run_date;
streaks/persistence advance ONLY when that quarter differs from the stored one — a
same-quarter re-run refreshes ranks and gate verdicts (and can still exit or seat a
name) without handing anyone an unearned "second quarter of evidence".

Bootstrap (first run, msg 58 "PIT-bootstrap"): pool members already passing gate+rank
enter immediately with since = current quarter; every other bench candidate — the
gate-passing names ranked just outside the seats — starts on the bench with streak 1,
so a first run really does produce squad AND bench. The squad never exceeds SLOTS; a
free slot with no proven candidate stays open ("liever cash dan een kandidaat zonder
bewijs").

The OPTIONAL fragility gate (docs/INVERSION-DESIGN.md §6, `update(..., fragility_gate=
True)`, `grade.py --fragility-gate`): a Ruinous inversion verdict blocks ENTRY — the name
is dropped from the entry pool, so it can neither bootstrap-seat nor be promoted. It never
forces an exit: selling is a different decision (§4.7), and this layer has earned no say
in it. A blocked name stays a bench candidate and its bench entry records the verdict, so
the block is visible rather than a silent deletion.

**It is off by default, and that is a decision, not an oversight.** The v3 entry rules
earned their place through the blind walk-forward of msgs 49-50; this layer has no such
evidence. Switching it on by default would trade a validated rule for a plausible one on
the strength of it reading well — the same trade SCORECARD-DESIGN §6 refuses for the
scorecard. With the gate off, `update()` is bit-for-bit the function it was before the
inversion layer existed, verdicts on the rows or not. Validating it is the same exercise as
before: re-run the walk-forward with the gate on and compare against the pre-registered
criterion.

`update()` is pure (no I/O, no clock); load/save/CLI wrap it. Transfers are
append-only with dated NL reasons (msg 57-58 phrasing).
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from scoring import EXIT_RANK, EXIT_V_PCTL, GATE_V_PCTL, PERSISTENCE_QUARTERS, SLOTS

STATE_FILE = "formation-state.json"
_NL_NUMBERS = {1: "één", 2: "twee", 3: "drie", 4: "vier", 5: "vijf"}

# The one verdict the optional §6 gate acts on. INVERSION-DESIGN §4 defines it as "has
# already destroyed owner capital, or is built to" (>= 2 severe probes) — the only verdict
# unambiguous enough to keep a name out of the squad. Fragile names are reported, not
# blocked: one named way of breaking is a judgement for the owner, not a rule.
GATE_VERDICT = "Ruinous"


def bench_rank() -> int:
    """Bench band bound: still-plausible entries are the gate-passing names down to the
    rank at which a SEATED name would be sold (§4.7 EXIT_RANK) — below that line a name
    is not a candidate at all and collects no evidence. Read at call time, so a backtest
    sweep that moves the exit rank moves the bench band with it."""
    return EXIT_RANK


def quarter_of(run_date: str) -> str:
    """Calendar quarter key of an ISO date (§3.4): '2026-07-30' -> '2026Q3'."""
    d = date.fromisoformat(run_date)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def _nl_count(n: int) -> str:
    return _NL_NUMBERS.get(n, str(n))


def verdict_of(row: dict) -> str | None:
    """The inversion verdict on one §3.3 row, or None when that layer had no answer.

    grade.py stores the raw result under "inversion" and the scorecard carries the same
    projection; the card is read first because its "verdict" key is guaranteed present
    (INVERSION-DESIGN §5). Rows written before this layer existed simply have neither."""
    card = (row.get("scorecard") or {}).get("inversion")
    for source in (card, row.get("inversion")):
        if isinstance(source, dict) and source.get("verdict"):
            return str(source["verdict"])
    return None


def gate_blocked(scored: list[dict]) -> dict[str, str]:
    """{symbol: verdict} for every row the §6 gate would keep out of the entry pool.

    Computed regardless of whether the gate is on — it costs nothing and keeps the two
    call sites (the pool and the bench's blocked marker) reading one rule."""
    blocked = {}
    for row in scored:
        verdict = verdict_of(row)
        if verdict and verdict.strip().lower() == GATE_VERDICT.lower():
            blocked[row["symbol"]] = verdict
    return blocked


def gate_coverage(scored: list[dict], blocked: dict[str, str]) -> dict:
    """What the §6 gate actually SAW this run -> {judged, unjudged, blocked}.

    A gate can only judge a name that has a verdict, and in the normal deployment only the
    quarter of the universe with a §3.6 weekly grid does. A name with no verdict — or an
    Unknown one, which §7 says is never to be read as safe — passes the gate in silence, so
    "gate ON" on its own tells the operator nothing about how much of the field it looked
    at. This records it; without it a run where the gate judged NOBODY still announces
    itself as blocking."""
    judged = [row["symbol"] for row in scored if verdict_of(row)]
    return {"judged": len(judged),
            "unjudged": len(scored) - len(judged),
            "blocked": sorted(blocked)}


def _views(scored: list[dict], blocked: dict | None = None
           ) -> tuple[dict, dict, dict, list[str], list[str]]:
    """Per-run views over §3.3 scored rows -> (rank, v_pctl, veto_reason, pool, band).

    rank: quality rank 1..N over names with a quality_score (desc, symbol tiebreak);
    v_pctl: V pillar score (the sector percentile of owner-FCF yield, §4.7);
    veto_reason: symbol -> reason for every vetoed name;
    pool: entry pool in rank order — rank <= SLOTS AND V-percentile >= GATE_V_PCTL,
    minus anything in `blocked` (the §6 fragility gate, empty unless it is switched on);
    band: bench candidates in rank order — the same gate, rank <= bench_rank() (a
    superset of the pool: the pool is what may be SEATED, the band what may WAIT). A
    blocked name stays in the band on purpose: it keeps waiting, visibly, instead of
    vanishing from the report."""
    blocked = blocked or {}
    ranked = sorted((s for s in scored if s.get("quality_score") is not None),
                    key=lambda s: (-s["quality_score"], s["symbol"]))
    rank = {s["symbol"]: i + 1 for i, s in enumerate(ranked)}
    v_pctl = {s["symbol"]: s["pillars"]["v"] for s in ranked}
    veto_reason = {s["symbol"]: (s.get("veto") or {}).get("reason") or "veto"
                   for s in scored if (s.get("veto") or {}).get("vetoed")}
    gated = [s["symbol"] for s in ranked if v_pctl[s["symbol"]] >= GATE_V_PCTL]
    pool = [sym for sym in gated if rank[sym] <= SLOTS and sym not in blocked]
    band = [sym for sym in gated if rank[sym] <= bench_rank()]
    return rank, v_pctl, veto_reason, pool, band


def _transfer(run_date: str, action: str, symbol: str, reason: str) -> dict:
    return {"date": run_date, "action": action, "symbol": symbol, "reason": reason}


def _sorted_squad(squad: list[dict]) -> list[dict]:
    """Stable display order: by refreshed quality rank (unranked last), then symbol."""
    return sorted(squad, key=lambda m: (m["quality_rank"] is None,
                                        m["quality_rank"] or 0, m["symbol"]))


def _bench_entry(symbol: str, streak: int, blocked: dict) -> dict:
    """One §3.4 bench member. The optional §6 block rides along ONLY when it applies, so a
    default run's state file is byte-for-byte the file it has always been."""
    entry = {"symbol": symbol, "streak": streak, "needed": PERSISTENCE_QUARTERS}
    if symbol in blocked:
        entry["blocked"] = blocked[symbol]
    return entry


def _bootstrap(rank: dict, pool: list[str], band: list[str], quarter: str, run_date: str,
               blocked: dict | None = None
               ) -> tuple[list[dict], list[dict], list[dict]]:
    """§5.6 first run: entry-pool members (gate + rank <= SLOTS) take the seats, in rank
    order, up to SLOTS; every remaining bench candidate — pool overflow first, then the
    gate-passing names ranked just outside the seats (up to bench_rank()) — starts on the
    bench with streak 1, so it can be promoted once it has both the evidence and a
    place in the entry pool."""
    blocked = blocked or {}
    squad, transfers = [], []
    for sym in pool:
        if len(squad) >= SLOTS:
            break
        squad.append({"symbol": sym, "since": quarter, "entered_date": run_date,
                      "quality_rank": rank[sym], "streak": 1})
        transfers.append(_transfer(
            run_date, "in", sym,
            f"erin — bootstrap: rang {rank[sym]} binnen de top-{SLOTS} "
            f"én door de prijspoort"))
    seated = {m["symbol"] for m in squad}
    bench = [_bench_entry(sym, 1, blocked) for sym in band if sym not in seated]
    return squad, bench, transfers


def update(state: dict | None, scored: list[dict], run_date: str, *,
           fragility_gate: bool = False) -> tuple[dict, list[dict]]:
    """One formation tick (§4.7/§5.6, pure) -> (new state per §3.4, this run's transfers).

    Order: exits (always evaluated — a veto must bite even on a same-quarter re-run) ->
    squad rank refresh + streak advance (advance only on quarter change, msg 62) ->
    bench rebuild from the current candidate band (carried streaks; +1 only on quarter
    change; a name that fell out of the band loses its consecutive streak) -> promotions
    (streak >= PERSISTENCE_QUARTERS AND back inside the entry pool, rank order, only
    while a slot is open).

    `fragility_gate` is INVERSION-DESIGN §6, and it is OFF by default: with it off this
    function does not read the verdicts at all and produces exactly the state it produced
    before that layer existed (see the module docstring for why — the v3 rules are
    walk-forward validated, this layer is not). With it on, a Ruinous verdict removes the
    name from the ENTRY POOL only: it cannot be seated or promoted, it is not sold, and it
    stays on the bench carrying the verdict that blocked it."""
    quarter = quarter_of(run_date)
    blocked = gate_blocked(scored) if fragility_gate else {}
    rank, v_pctl, veto_reason, pool, band = _views(scored, blocked)
    gate_state = ({"fragility_gate": GATE_VERDICT,
                   "fragility_gate_coverage": gate_coverage(scored, blocked)}
                  if fragility_gate else {})

    if not state or not state.get("quarter"):
        squad, bench, new_transfers = _bootstrap(rank, pool, band, quarter, run_date,
                                                 blocked)
        history = list((state or {}).get("transfers") or [])
        return {"as_of": run_date, "quarter": quarter, "slots": SLOTS,
                "squad": _sorted_squad(squad), "bench": bench,
                "transfers": history + new_transfers, **gate_state}, new_transfers

    new_quarter = quarter != state["quarter"]
    new_transfers: list[dict] = []

    # Exits — ONLY veto / rank > EXIT_RANK / V-percentile < EXIT_V_PCTL (§4.7). A squad
    # member absent from this run's scored rows (no cache, INSUFFICIENT) fails no test
    # and simply stays — no evidence is never a sell signal.
    squad = []
    for member in state["squad"]:
        m, sym = dict(member), member["symbol"]
        if sym in veto_reason:
            new_transfers.append(_transfer(run_date, "out", sym,
                                           f"eruit — veto: {veto_reason[sym]}"))
            continue
        r = rank.get(sym)
        if r is not None and r > EXIT_RANK:
            new_transfers.append(_transfer(
                run_date, "out", sym,
                f"eruit — rang boven de verkoopgrens ({EXIT_RANK}): rang {r}"))
            continue
        v = v_pctl.get(sym)
        if v is not None and v < EXIT_V_PCTL:
            new_transfers.append(_transfer(
                run_date, "out", sym,
                f"eruit — extreme duurte: V-percentiel {v:.0f} onder {EXIT_V_PCTL:.0f}"))
            continue
        if r is not None:
            m["quality_rank"] = r
        if new_quarter:
            m["streak"] += 1
        squad.append(m)

    # Bench — the candidate band minus the squad, streaks carried; consecutive-quarter
    # discipline (a name that left the band starts over at 1 when it returns).
    in_squad = {m["symbol"] for m in squad}
    prev_streak = {b["symbol"]: b["streak"] for b in state["bench"]}
    bench = []
    for sym in band:
        if sym in in_squad:
            continue
        streak = prev_streak.get(sym)
        streak = 1 if streak is None else streak + 1 if new_quarter else streak
        bench.append(_bench_entry(sym, streak, blocked))

    # Promotions — bench members with the evidence AND a place in the entry pool take
    # open slots in rank order; the slot cap is absolute and an unfilled slot stays open
    # (cash) rather than seating thin evidence.
    in_pool = set(pool)
    for cand in [b for b in bench
                 if b["streak"] >= PERSISTENCE_QUARTERS and b["symbol"] in in_pool]:
        if len(squad) >= SLOTS:
            break
        sym = cand["symbol"]
        squad.append({"symbol": sym, "since": quarter, "entered_date": run_date,
                      "quality_rank": rank[sym], "streak": cand["streak"]})
        bench.remove(cand)
        new_transfers.append(_transfer(
            run_date, "in", sym,
            f"erin — {_nl_count(cand['streak'])} kwartalen bewijs én door de prijspoort"))

    return {"as_of": run_date, "quarter": quarter, "slots": SLOTS,
            "squad": _sorted_squad(squad), "bench": bench,
            "transfers": list(state.get("transfers") or []) + new_transfers,
            **gate_state}, new_transfers


# ------------------------------------------------------------------- state file I/O

def load_state(path: str | Path = STATE_FILE) -> dict | None:
    """formation-state.json -> dict, or None when absent/unparsable (-> bootstrap)."""
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def save_state(state: dict, path: str | Path = STATE_FILE) -> None:
    """Atomic write (tmp + os.replace), 2-space indent for the human-readable state."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False, allow_nan=False),
                   encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- display

def render(state: dict) -> str:
    """NL text view of a §3.4 state (the --show CLI and grade.py's console echo)."""
    lines = [f"De Formatie {state['quarter']} (per {state['as_of']}) — "
             f"{len(state['squad'])}/{state['slots']} plekken bezet"]
    lines.append("Opstelling:" if state["squad"] else "Opstelling: leeg")
    for i, m in enumerate(state["squad"], 1):
        r = m["quality_rank"] if m["quality_rank"] is not None else "?"
        lines.append(f"  {i:2d}. {m['symbol']:<10} rang {r:>3} · in sinds {m['since']} "
                     f"· streak {m['streak']}")
    lines.append("Bank:" if state["bench"] else "Bank: leeg")
    for b in state["bench"]:
        blocked = (f" · geblokkeerd door de fragiliteitspoort ({b['blocked']})"
                   if b.get("blocked") else "")
        lines.append(f"  {b['symbol']:<10} {b['streak']}/{b['needed']} "
                     f"kwartalen bewijs{blocked}")
    recent = state["transfers"][-5:]
    lines.append("Transfers (laatste 5):" if recent else "Transfers: nog geen")
    for t in recent:
        lines.append(f"  {t['date']} · {t['symbol']}: {t['reason']}")
    open_slots = state["slots"] - len(state["squad"])
    lines.append(f"Open plekken: {open_slots} — blijven cash." if open_slots
                 else "Geen open plekken.")
    if state.get("fragility_gate"):
        lines.append(f"Fragiliteitspoort AAN: een {state['fragility_gate']}-verdict "
                     f"blokkeert toetreding (INVERSION-DESIGN §6, standaard uit).")
        lines.append("  " + gate_coverage_line(state))
    return "\n".join(lines)


def gate_coverage_line(state: dict) -> str:
    """One sentence saying how much of the field the §6 gate could judge."""
    cov = state.get("fragility_gate_coverage") or {}
    judged, unjudged = cov.get("judged"), cov.get("unjudged")
    if judged is None or unjudged is None:
        return "beoordeelde kandidaten niet vastgelegd — onbekend is niet hetzelfde als veilig."
    total = judged + unjudged
    tail = (f" · {len(cov.get('blocked') or [])} geblokkeerd"
            if cov.get("blocked") else " · niemand geblokkeerd")
    return (f"{judged} van {total} kandidaten beoordeeld, {unjudged} zonder verdict "
            f"(niet geblokkeerd){tail}.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="v3 owner-mode formation state (spec §5.6)")
    ap.add_argument("--show", action="store_true", help="print the current formation")
    ap.add_argument("--state", default=STATE_FILE, help="formation-state.json path (§3.4)")
    args = ap.parse_args(argv)
    if not args.show:
        ap.print_help()
        return 0
    state = load_state(args.state)
    if state is None:
        print(f"Geen formatie-state gevonden ({args.state}) — "
              f"de eerste grade.py-run bootstrapt hem.")
        return 1
    print(render(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
