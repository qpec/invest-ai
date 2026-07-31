"""Offline tests for formation.py — the frozen v3 owner-mode rules (spec §4.7, §5.6,
§3.4; msgs 57-58, 62). Synthetic scored lists across simulated quarters; update() is
pure, so no files except one save/load round-trip. Constants come from scoring.py."""
from __future__ import annotations

import json

import formation
import scoring

Q3_A = "2026-07-29"      # 2026Q3
Q3_B = "2026-07-30"      # same quarter, next day (msg 62 re-run case)
Q4 = "2026-10-05"        # 2026Q4
Q1_27 = "2027-01-05"     # 2027Q1
Q2_27 = "2027-04-06"     # 2027Q2


def graded(symbol, quality, v=50.0):
    """Minimal §3.3 scored row for a graded name (only the fields formation reads)."""
    return {"symbol": symbol, "grade": "B", "composite": quality,
            "quality_score": quality,
            "pillars": {"v": v, "q": quality, "g": 50.0, "d": 50.0, "m": 50.0},
            "veto": {"vetoed": False, "reason": "", "penalty": 0}}


def vetoed(symbol, reason="leverage veto: net debt/EBITDA 6.1 > 4.0"):
    return {"symbol": symbol, "grade": "VETOED", "composite": None,
            "quality_score": None,
            "pillars": {"v": None, "q": None, "g": None, "d": None, "m": None},
            "veto": {"vetoed": True, "reason": reason, "penalty": 0}}


def squad_syms(state):
    return {m["symbol"] for m in state["squad"]}


def bench_by_sym(state):
    return {b["symbol"]: b for b in state["bench"]}


# ------------------------------------------------------------------ quarter key

def test_quarter_of_calendar_quarters():
    assert formation.quarter_of("2026-01-15") == "2026Q1"
    assert formation.quarter_of("2026-06-30") == "2026Q2"
    assert formation.quarter_of("2026-07-30") == "2026Q3"
    assert formation.quarter_of("2026-12-31") == "2026Q4"


# -------------------------------------------------------------------- bootstrap

def test_bootstrap_gate_and_rank_passers_enter():
    scored = [graded("AAA", 90, v=80), graded("BBB", 80, v=30),
              graded("CCC", 70, v=10),                    # gate fail: no pool, no squad
              vetoed("VET")]
    state, transfers = formation.update(None, scored, Q3_A)
    assert state["quarter"] == "2026Q3"
    assert state["as_of"] == Q3_A
    assert state["slots"] == scoring.SLOTS == 15
    assert squad_syms(state) == {"AAA", "BBB"}
    for m in state["squad"]:
        assert m["since"] == "2026Q3"
        assert m["entered_date"] == Q3_A
        assert m["streak"] == 1
    ranks = {m["symbol"]: m["quality_rank"] for m in state["squad"]}
    assert ranks == {"AAA": 1, "BBB": 2}
    assert state["bench"] == []                           # gate-failers never benched
    assert [(t["action"], t["symbol"]) for t in transfers] == [("in", "AAA"), ("in", "BBB")]
    assert all("bootstrap" in t["reason"] and "prijspoort" in t["reason"]
               for t in transfers)
    assert state["transfers"] == transfers                # append-only history seeded


def test_bootstrap_fills_the_squad_and_a_real_bench():
    # msg 58's first formation was 14 seated + 5 on the bench "waiting one more quarter
    # for their evidence" — with 30 gate-passing names a bootstrap must produce BOTH.
    scored = [graded(f"N{i:02d}", 100.0 - i, v=50) for i in range(30)]
    state, transfers = formation.update(None, scored, Q3_A)
    assert len(state["squad"]) == scoring.SLOTS == 15            # the seats, rank order
    assert squad_syms(state) == {f"N{i:02d}" for i in range(15)}
    bench = state["bench"]
    assert [b["symbol"] for b in bench] == [f"N{i:02d}" for i in range(15, 30)]
    assert all(b == {"symbol": b["symbol"], "streak": 1,
                     "needed": scoring.PERSISTENCE_QUARTERS} for b in bench)
    assert len(transfers) == 15                                 # bench seats nobody yet
    assert {t["symbol"] for t in transfers} == squad_syms(state)


def test_bench_band_stops_at_the_sell_line():
    # A candidate ranked past EXIT_RANK is not a candidate at all: it would be sold the
    # day it were seated, so it collects no evidence.
    scored = [graded(f"N{i:02d}", 100.0 - i, v=50)
              for i in range(scoring.EXIT_RANK + 5)]
    state, _ = formation.update(None, scored, Q3_A)
    assert len(state["squad"]) == scoring.SLOTS
    assert len(state["bench"]) == scoring.EXIT_RANK - scoring.SLOTS
    assert state["bench"][-1]["symbol"] == f"N{scoring.EXIT_RANK - 1:02d}"
    assert formation.bench_rank() == scoring.EXIT_RANK


def test_bench_candidate_from_outside_the_seats_is_promoted_when_it_rises():
    # Bench evidence is only worth something when the name is ALSO back in the entry
    # pool (rank <= SLOTS) and a slot is open — evidence plus a place, never one alone.
    seated = [graded(f"S{i:02d}", 100.0 - i, v=50) for i in range(15)]
    waiting = graded("WAIT", 80.0, v=50)                        # rank 16: bench, not pool
    state, _ = formation.update(None, seated + [waiting], Q3_A)
    assert "WAIT" not in squad_syms(state)
    assert bench_by_sym(state)["WAIT"]["streak"] == 1

    state, transfers = formation.update(state, seated + [waiting], Q4)
    assert bench_by_sym(state)["WAIT"]["streak"] == 2           # evidence, but rank 16
    assert transfers == []                                      # ...so still no seat

    # A veto frees a slot AND WAIT rises into the top-15: now it may be seated.
    dropped = seated[:14] + [vetoed("S14"), graded("WAIT", 95.0, v=50)]
    state, transfers = formation.update(state, dropped, Q1_27)
    assert "WAIT" in squad_syms(state)
    assert [(t["action"], t["symbol"]) for t in transfers] == [("out", "S14"),
                                                              ("in", "WAIT")]


def test_bootstrap_gate_boundary_is_inclusive():
    state, _ = formation.update(None, [graded("EDGE", 90, v=scoring.GATE_V_PCTL)], Q3_A)
    assert squad_syms(state) == {"EDGE"}                  # V-pctl == 20.0 passes (>=)


# ------------------------------------------------------- persistence: bench -> squad

def test_bench_to_squad_after_two_quarters():
    base = [graded("AAA", 90, v=80), graded("BBB", 80, v=30)]
    state, _ = formation.update(None, base, Q3_A)

    with_c = base + [graded("CCC", 75, v=50)]
    state, transfers = formation.update(state, with_c, Q4)      # C's first quarter
    assert transfers == []
    assert "CCC" not in squad_syms(state)
    assert bench_by_sym(state)["CCC"] == {"symbol": "CCC", "streak": 1,
                                          "needed": scoring.PERSISTENCE_QUARTERS}
    assert all(m["streak"] == 2 for m in state["squad"])        # quarter tick advanced

    state, transfers = formation.update(state, with_c, Q1_27)   # C's second quarter
    assert "CCC" in squad_syms(state)
    assert state["bench"] == []
    member = next(m for m in state["squad"] if m["symbol"] == "CCC")
    assert member["since"] == "2027Q1"
    assert member["entered_date"] == Q1_27
    assert member["streak"] == 2
    assert [t["symbol"] for t in transfers] == ["CCC"]
    assert transfers[0]["reason"] == \
        "erin — twee kwartalen bewijs én door de prijspoort"    # msg 57 phrasing
    assert state["transfers"][-1] == transfers[0]               # appended to history


def test_gate_blocks_entry_and_streak_accrual():
    state, _ = formation.update(None, [graded("AAA", 90, v=80)], Q3_A)
    hot = graded("HOT", 95, v=10)                               # rank 1, gate fail
    for run_date in (Q4, Q1_27):
        state, transfers = formation.update(
            state, [graded("AAA", 90, v=80), hot], run_date)
        assert "HOT" not in squad_syms(state)
        assert "HOT" not in bench_by_sym(state)                 # no pool -> no streak
        assert transfers == []
    # Once the price gate opens, evidence starts at 1 — the blocked quarters never count.
    ok = graded("HOT", 95, v=25)
    state, _ = formation.update(state, [graded("AAA", 90, v=80), ok], Q2_27)
    assert bench_by_sym(state)["HOT"]["streak"] == 1
    assert "HOT" not in squad_syms(state)


# ------------------------------------------------------------------------- exits

def test_exit_on_rank_above_sell_line():
    state, _ = formation.update(None, [graded("AAA", 100, v=50)], Q3_A)
    crowd = [graded(f"F{i:02d}", 90.0 - i, v=50) for i in range(44)]
    state, transfers = formation.update(state, crowd + [graded("AAA", 1.0, v=50)], Q4)
    assert "AAA" not in squad_syms(state)
    out = [t for t in transfers if t["action"] == "out"]
    assert [t["symbol"] for t in out] == ["AAA"]
    assert f"eruit — rang boven de verkoopgrens ({scoring.EXIT_RANK})" in out[0]["reason"]
    assert "rang 45" in out[0]["reason"]


def test_rank_at_40_stays():
    state, _ = formation.update(None, [graded("AAA", 100, v=50)], Q3_A)
    crowd = [graded(f"F{i:02d}", 90.0 - i, v=50) for i in range(39)]
    state, transfers = formation.update(state, crowd + [graded("AAA", 1.0, v=50)], Q4)
    assert "AAA" in squad_syms(state)                           # rank 40 == grens: blijft
    assert next(m for m in state["squad"] if m["symbol"] == "AAA")["quality_rank"] == 40
    assert not any(t["action"] == "out" for t in transfers)


def test_exit_on_veto():
    state, _ = formation.update(None, [graded("AAA", 90, v=80),
                                       graded("BBB", 80, v=30)], Q3_A)
    state, transfers = formation.update(
        state, [vetoed("AAA", "cash-flow quality: OCF leans 77% on credit-loss"),
                graded("BBB", 80, v=30)], Q4)
    assert squad_syms(state) == {"BBB"}
    out = [t for t in transfers if t["action"] == "out"]
    assert out[0]["symbol"] == "AAA"
    assert out[0]["reason"].startswith("eruit — veto: cash-flow quality")
    assert next(m for m in state["squad"] if m["symbol"] == "BBB")["streak"] == 2


def test_exit_on_extreme_overvaluation():
    state, _ = formation.update(None, [graded("AAA", 90, v=80)], Q3_A)
    state, transfers = formation.update(state, [graded("AAA", 90, v=3.0)], Q4)
    assert "AAA" not in squad_syms(state)
    assert "extreme duurte" in transfers[0]["reason"]


def test_missing_or_insufficient_member_stays():
    # Exit ONLY on veto / rank / duurte — a name absent from this run's scored rows
    # (no cache, INSUFFICIENT) fails no test and keeps its seat.
    state, _ = formation.update(None, [graded("AAA", 90, v=80),
                                       graded("BBB", 80, v=30)], Q3_A)
    state, transfers = formation.update(state, [graded("BBB", 80, v=30)], Q4)
    assert squad_syms(state) == {"AAA", "BBB"}
    assert transfers == []
    aaa = next(m for m in state["squad"] if m["symbol"] == "AAA")
    assert aaa["streak"] == 2                                   # tenure still advances
    assert aaa["quality_rank"] == 1                             # last known rank kept


# ------------------------------------------------- same-quarter re-run (msg 62 fix)

def test_same_quarter_rerun_advances_nothing():
    base = [graded("AAA", 90, v=80), graded("BBB", 80, v=30)]
    state, _ = formation.update(None, base, Q3_A)

    with_c = base + [graded("CCC", 75, v=50)]
    state1, t1 = formation.update(state, with_c, Q4)            # CCC benched, streak 1
    assert bench_by_sym(state1)["CCC"]["streak"] == 1

    state2, t2 = formation.update(state1, with_c, Q4)           # same-quarter re-run
    assert t2 == []                                             # no duplicate transfers
    assert state2["transfers"] == state1["transfers"]
    assert state2["squad"] == state1["squad"]                   # identical streaks/ranks
    assert state2["bench"] == state1["bench"]                   # CCC still 1/2

    # ...and only a REAL quarter change hands out the second quarter of evidence:
    state4, t4 = formation.update(state2, with_c, Q1_27)
    assert "CCC" in squad_syms(state4)
    assert [t["symbol"] for t in t4] == ["CCC"]


def test_same_quarter_rerun_still_refreshes_gates_and_exits():
    # Refresh without streak advance (msg 62): fresh data may still veto a member out
    # or admit a new bench candidate mid-quarter — streaks just never move.
    base = [graded("AAA", 90, v=80), graded("BBB", 80, v=30)]
    state, _ = formation.update(None, base, Q3_A)
    refreshed = [vetoed("AAA"), graded("BBB", 80, v=30), graded("NEW", 85, v=60)]
    state, transfers = formation.update(state, refreshed, Q3_B)
    assert squad_syms(state) == {"BBB"}
    assert {t["action"] for t in transfers} == {"out"}
    assert bench_by_sym(state)["NEW"]["streak"] == 1
    member = next(m for m in state["squad"] if m["symbol"] == "BBB")
    assert member["streak"] == 1                                # same quarter: no advance


# --------------------------------------------------------------- slot discipline

def test_slot_cap_holds_at_15():
    fifteen = [graded(f"S{i:02d}", 90.0 - i, v=50) for i in range(15)]
    state, transfers = formation.update(None, fifteen, Q3_A)
    assert len(state["squad"]) == 15
    assert len(transfers) == 15

    crowded = [graded("NEW", 95, v=50)] + fifteen               # NEW takes rank 1
    state, transfers = formation.update(state, crowded, Q4)
    assert len(state["squad"]) == 15                            # S14 (rank 16) stays put
    assert "NEW" not in squad_syms(state)
    assert bench_by_sym(state)["NEW"]["streak"] == 1
    assert transfers == []

    state, transfers = formation.update(state, crowded, Q1_27)  # proven, but squad full
    assert len(state["squad"]) == 15
    assert "NEW" not in squad_syms(state)
    assert bench_by_sym(state)["NEW"]["streak"] == 2            # keeps waiting on bench
    assert transfers == []


def test_open_slot_stays_cash():
    two = [graded("AAA", 90, v=80), graded("BBB", 80, v=30)]
    state, _ = formation.update(None, two, Q3_A)
    assert state["slots"] - len(state["squad"]) == 13           # open slots stay open
    state, transfers = formation.update(state, two, Q4)
    assert len(state["squad"]) == 2                             # never filled with filler
    assert state["bench"] == []
    assert transfers == []


def test_freed_slot_goes_to_proven_bench_member():
    fifteen = [graded(f"S{i:02d}", 90.0 - i, v=50) for i in range(15)]
    state, _ = formation.update(None, fifteen, Q3_A)
    crowded = [graded("NEW", 95, v=50)] + fifteen
    state, _ = formation.update(state, crowded, Q4)             # NEW benched, streak 1
    dropped = [graded("NEW", 95, v=50)] + fifteen[:14] + [vetoed("S14")]
    state, transfers = formation.update(state, dropped, Q1_27)  # veto frees a slot
    assert "S14" not in squad_syms(state)
    assert "NEW" in squad_syms(state)                           # streak 2 + open slot
    assert [(t["action"], t["symbol"]) for t in transfers] == \
        [("out", "S14"), ("in", "NEW")]


# ------------------------------------------------------------------ state file I/O

def test_save_load_roundtrip_and_missing(tmp_path):
    path = tmp_path / "formation-state.json"
    assert formation.load_state(path) is None
    state, _ = formation.update(None, [graded("AAA", 90, v=80)], Q3_A)
    formation.save_state(state, path)
    assert formation.load_state(path) == state
    assert json.loads(path.read_text(encoding="utf-8")) == state
    junk = tmp_path / "junk.json"
    junk.write_text('{"quarter": "2026', encoding="utf-8")      # torn write
    assert formation.load_state(junk) is None


def test_render_and_cli_show(tmp_path, capsys):
    path = tmp_path / "formation-state.json"
    assert formation.main(["--show", "--state", str(path)]) == 1
    state, _ = formation.update(None, [graded("AAA", 90, v=80)], Q3_A)
    formation.save_state(state, path)
    assert formation.main(["--show", "--state", str(path)]) == 0
    out = capsys.readouterr().out
    assert "De Formatie 2026Q3" in out
    assert "AAA" in out
    assert "Open plekken: 14" in out
