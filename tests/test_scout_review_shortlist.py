"""Stage-2 shortlist selection (design Part A + parent design §4): top-per-tier by composite
+ every Outside-tier A, VETOED/INSUFFICIENT excluded, deterministic order. READ-only over
GradedName - never mutates grading."""
from agentcy import scout_review as sr
from agentcy import scout_grade as sg


def _g(sym, tier, comp, grade):
    # only the fields shortlist reads need real values; the rest are placeholders
    return sg.GradedName(sym, "Technology", tier, 60.0, 60.0, 60.0, 60.0, 60.0, comp, grade, "")


def test_top_per_tier_by_composite_default_ten():
    rows = [_g(f"C{i}", "Core", float(i), "B") for i in range(15)]  # 15 Core names, comp 0..14
    picked = sr.select_shortlist(rows)
    core = [g for g in picked if g.tier == "Core"]
    assert len(core) == 10                                   # capped at SHORTLIST_PER_TIER
    assert [g.symbol for g in core] == [f"C{i}" for i in range(14, 4, -1)]  # top 10 by comp desc


def test_outside_a_always_included_even_beyond_top_ten():
    # 12 Outside names; the two A-grades are ranked #11 and #12 by composite but must STILL surface
    rows = [_g(f"O{i}", "Outside", float(i), "B") for i in range(10)]      # comp 0..9, B
    rows += [_g("OA1", "Outside", 100.0, "A"), _g("OA2", "Outside", 99.0, "A")]  # top A-grades
    # make the A-grades rank OUTSIDE the top-10-by-composite by adding higher-comp B names
    rows += [_g(f"OB{i}", "Outside", 200.0 + i, "B") for i in range(10)]
    picked = sr.select_shortlist(rows, per_tier=10)
    syms = {g.symbol for g in picked}
    assert "OA1" in syms and "OA2" in syms                   # Outside-A star: never dropped
    # no duplicates even though OA* are both top-per-tier-eligible and Outside-A
    assert len([g for g in picked if g.symbol == "OA1"]) == 1


def test_vetoed_and_insufficient_excluded():
    rows = [
        _g("GOOD", "Core", 80.0, "A"),
        sg.GradedName("VETO", "Technology", "Core", None, None, None, None, None, None, "VETOED", "lev"),
        sg.GradedName("THIN", "Technology", "Core", None, None, None, None, None, None, "INSUFFICIENT", "thin"),
    ]
    picked = sr.select_shortlist(rows)
    assert [g.symbol for g in picked] == ["GOOD"]


def test_deterministic_order_tier_then_comp_then_ticker():
    rows = [
        _g("ADJ", "Adjacent", 70.0, "B"),
        _g("COR2", "Core", 70.0, "B"),
        _g("COR1", "Core", 70.0, "B"),   # same comp as COR2 -> ticker asc breaks the tie
        _g("OUT", "Outside", 90.0, "A"),
    ]
    picked = sr.select_shortlist(rows)
    assert [g.symbol for g in picked] == ["COR1", "COR2", "ADJ", "OUT"]
