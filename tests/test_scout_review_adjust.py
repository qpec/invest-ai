"""Stage-2 bounded one-band adjustment truth table (design Part A / parent §4). READS
GradedName + Verdict; NEVER moves the composite number - only the letter, one band, reasoned."""
from agentcy import scout_review as sr
from agentcy import scout_grade as sg


def g(grade, *, v=60.0, q=60.0, g_=60.0, d=60.0, m=60.0, comp=60.0):
    # GradedName field order: symbol, sector, tier, v, q, g, d, m, composite, grade, note
    return sg.GradedName("X", "Technology", "Core", v, q, g_, d, m, comp, grade, "")


def test_fad_flag_demotes_one_band():
    final, reason = sr.adjust_grade(g("B"), sr.Verdict(fad="flag", reason="AI-branded"))
    assert final == "C"
    assert "demote" in reason.lower() and "fad" in reason.lower()


def test_mgmt_red_flag_demotes_one_band():
    final, reason = sr.adjust_grade(g("A"), sr.Verdict(mgmt="red-flag", reason="related-party"))
    assert final == "B"
    assert "demote" in reason.lower()


def test_demote_clamps_at_f():
    final, reason = sr.adjust_grade(g("F", comp=10.0), sr.Verdict(fad="flag"))
    assert final == "F"                                   # cannot go below F


def test_promote_all_four_good_and_no_pillar_below_50():
    v = sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok")
    final, reason = sr.adjust_grade(g("B", v=55.0, q=80.0, g_=70.0, d=70.0, m=65.0), v)
    assert final == "A"
    assert "promote" in reason.lower()


def test_promote_clamps_at_a():
    v = sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok")
    final, _ = sr.adjust_grade(g("A", v=90.0, q=90.0, g_=90.0, d=90.0, m=90.0, comp=90.0), v)
    assert final == "A"


def test_no_promote_when_a_pillar_below_50():
    v = sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok")
    final, reason = sr.adjust_grade(g("B", v=49.0, q=80.0, g_=80.0, d=80.0, m=80.0), v)
    assert final == "B"                                   # gated: a pillar < 50 blocks promotion
    assert "no qualitative adjustment" in reason.lower() or "not promoted" in reason.lower()


def test_no_promote_when_growth_pillar_below_50():
    # RF1 (MAJOR): the promotion pillar-gate is the 5-pillar min(V,Q,G,D,M) >= 50.
    # G = 40 with V/Q/D/M all >= 50 and all four axes clear must NOT promote (G blocks it).
    v = sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok")
    final, reason = sr.adjust_grade(g("B", v=80.0, q=80.0, g_=40.0, d=80.0, m=80.0), v)
    assert final == "B"                                   # Growth pillar < 50 blocks promotion
    assert "no qualitative adjustment" in reason.lower() or "not promoted" in reason.lower()


def test_pending_axes_never_promote_and_never_demote():
    final, reason = sr.adjust_grade(g("B"), sr.Verdict(moat="confirmed"))  # other three pending
    assert final == "B"
    assert "no qualitative adjustment" in reason.lower()


def test_demote_beats_promote_when_both_would_apply():
    # all four "good" EXCEPT mgmt is a red-flag -> demotion wins, never promoted
    v = sr.Verdict(moat="confirmed", mgmt="red-flag", fad="clear", tier="ok")
    final, reason = sr.adjust_grade(g("B", v=80.0, q=80.0, g_=80.0, d=80.0, m=80.0), v)
    assert final == "C"
    assert "demote" in reason.lower()


def test_reason_always_returned_even_when_unchanged():
    final, reason = sr.adjust_grade(g("C"), sr.Verdict())   # all pending
    assert final == "C"
    assert reason                                            # never empty / never silent
