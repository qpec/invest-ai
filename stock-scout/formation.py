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

Quarter discipline (msg 62 fix): the quarter key is the calendar quarter of run_date;
streaks/persistence advance ONLY when that quarter differs from the stored one — a
same-quarter re-run refreshes ranks and gate verdicts (and can still exit or seat a
name) without handing anyone an unearned "second quarter of evidence".

Bootstrap (first run, msg 58 "PIT-bootstrap"): pool members already passing gate+rank
enter immediately with since = current quarter; any pool remainder that finds no open
slot goes to the bench with streak 1. The squad never exceeds SLOTS; a free slot with
no proven candidate stays open ("liever cash dan een kandidaat zonder bewijs").

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


def quarter_of(run_date: str) -> str:
    """Calendar quarter key of an ISO date (§3.4): '2026-07-30' -> '2026Q3'."""
    d = date.fromisoformat(run_date)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def _nl_count(n: int) -> str:
    return _NL_NUMBERS.get(n, str(n))


def _views(scored: list[dict]) -> tuple[dict, dict, dict, list[str]]:
    """Per-run views over §3.3 scored rows -> (rank, v_pctl, veto_reason, pool).

    rank: quality rank 1..N over names with a quality_score (desc, symbol tiebreak);
    v_pctl: V pillar score (the sector percentile of owner-FCF yield, §4.7);
    veto_reason: symbol -> reason for every vetoed name;
    pool: entry pool in rank order — rank <= SLOTS AND V-percentile >= GATE_V_PCTL."""
    ranked = sorted((s for s in scored if s.get("quality_score") is not None),
                    key=lambda s: (-s["quality_score"], s["symbol"]))
    rank = {s["symbol"]: i + 1 for i, s in enumerate(ranked)}
    v_pctl = {s["symbol"]: s["pillars"]["v"] for s in ranked}
    veto_reason = {s["symbol"]: (s.get("veto") or {}).get("reason") or "veto"
                   for s in scored if (s.get("veto") or {}).get("vetoed")}
    pool = [s["symbol"] for s in ranked
            if rank[s["symbol"]] <= SLOTS and v_pctl[s["symbol"]] >= GATE_V_PCTL]
    return rank, v_pctl, veto_reason, pool


def _transfer(run_date: str, action: str, symbol: str, reason: str) -> dict:
    return {"date": run_date, "action": action, "symbol": symbol, "reason": reason}


def _sorted_squad(squad: list[dict]) -> list[dict]:
    """Stable display order: by refreshed quality rank (unranked last), then symbol."""
    return sorted(squad, key=lambda m: (m["quality_rank"] is None,
                                        m["quality_rank"] or 0, m["symbol"]))


def _bootstrap(rank: dict, pool: list[str], quarter: str, run_date: str
               ) -> tuple[list[dict], list[dict], list[dict]]:
    """§5.6 first run: gate+rank passers enter with since = current quarter; any pool
    remainder beyond the open slots goes to the bench with streak 1."""
    squad, bench, transfers = [], [], []
    for sym in pool:
        if len(squad) < SLOTS:
            squad.append({"symbol": sym, "since": quarter, "entered_date": run_date,
                          "quality_rank": rank[sym], "streak": 1})
            transfers.append(_transfer(
                run_date, "in", sym,
                f"erin — bootstrap: rang {rank[sym]} binnen de top-{SLOTS} "
                f"én door de prijspoort"))
        else:
            bench.append({"symbol": sym, "streak": 1, "needed": PERSISTENCE_QUARTERS})
    return squad, bench, transfers


def update(state: dict | None, scored: list[dict], run_date: str
           ) -> tuple[dict, list[dict]]:
    """One formation tick (§4.7/§5.6, pure) -> (new state per §3.4, this run's transfers).

    Order: exits (always evaluated — a veto must bite even on a same-quarter re-run) ->
    squad rank refresh + streak advance (advance only on quarter change, msg 62) ->
    bench rebuild from the current pool (carried streaks; +1 only on quarter change;
    a name that fell out of the pool loses its consecutive streak) -> promotions
    (streak >= PERSISTENCE_QUARTERS, rank order, only while a slot is open)."""
    quarter = quarter_of(run_date)
    rank, v_pctl, veto_reason, pool = _views(scored)

    if not state or not state.get("quarter"):
        squad, bench, new_transfers = _bootstrap(rank, pool, quarter, run_date)
        history = list((state or {}).get("transfers") or [])
        return {"as_of": run_date, "quarter": quarter, "slots": SLOTS,
                "squad": _sorted_squad(squad), "bench": bench,
                "transfers": history + new_transfers}, new_transfers

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

    # Bench — the pool minus the squad, streaks carried; consecutive-quarter discipline.
    in_squad = {m["symbol"] for m in squad}
    prev_streak = {b["symbol"]: b["streak"] for b in state["bench"]}
    bench = []
    for sym in pool:
        if sym in in_squad:
            continue
        streak = prev_streak.get(sym)
        streak = 1 if streak is None else streak + 1 if new_quarter else streak
        bench.append({"symbol": sym, "streak": streak, "needed": PERSISTENCE_QUARTERS})

    # Promotions — proven bench members take open slots in rank order; the slot cap is
    # absolute and an unfilled slot stays open (cash) rather than seating thin evidence.
    for cand in [b for b in bench if b["streak"] >= PERSISTENCE_QUARTERS]:
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
            "transfers": list(state.get("transfers") or []) + new_transfers}, new_transfers


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
        lines.append(f"  {b['symbol']:<10} {b['streak']}/{b['needed']} kwartalen bewijs")
    recent = state["transfers"][-5:]
    lines.append("Transfers (laatste 5):" if recent else "Transfers: nog geen")
    for t in recent:
        lines.append(f"  {t['date']} · {t['symbol']}: {t['reason']}")
    open_slots = state["slots"] - len(state["squad"])
    lines.append(f"Open plekken: {open_slots} — blijven cash." if open_slots
                 else "Geen open plekken.")
    return "\n".join(lines)


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
