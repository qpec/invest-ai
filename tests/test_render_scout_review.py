"""Stage-2 annotated render: det grade -> badges -> one-band-adjusted final + reasons + honest
note; two skins from one context; lint-clean; pending name renders unchanged. Golden-backed."""
from agentcy.render.scout_review import ScoutReviewContext, render_scout_review
from agentcy.render.lint import lint, _BENCH
from agentcy import scout_review as sr
from agentcy import scout_grade as sg


def _ctx():
    shortlist = (
        sg.GradedName("MSFT", "Technology", "Core", 55.0, 80.0, 60.0, 70.0, 65.0, 72.0, "B", ""),
        sg.GradedName("FADS", "Technology", "Adjacent", 60.0, 60.0, 60.0, 60.0, 60.0, 66.0, "B", ""),
        sg.GradedName("PEND", "Technology", "Outside", 60.0, 60.0, 60.0, 60.0, 60.0, 55.0, "C", ""),
    )
    verdicts = {
        "MSFT": sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok",
                           reason="switching costs; founder-led; real trend"),
        "FADS": sr.Verdict(fad="flag", reason="AI-branded rollup"),
        # PEND: no verdict -> pending, grade unchanged
    }
    return ScoutReviewContext(as_of_label="Fri 10 Jul 2026", shortlist=shortlist,
                              verdicts=verdicts, evidence_note=sg.HONEST_EVIDENCE_NOTE)


def test_annotated_render_promote_demote_pending(golden):
    r = render_scout_review(_ctx())
    assert r.output_class == "notice"
    md = r.markdown
    # MSFT: all four clear + no pillar < 50 -> promoted B -> A, reason printed
    assert "promote one band (B -> A)" in md
    # FADS: fad flag -> demoted B -> C, reason printed
    assert "demote one band (B -> C)" in md and "fad" in md.lower()
    # PEND: no verdict -> unchanged, qualitative pending
    assert "pending" in md.lower()
    # honest evidence note present
    assert "promises nothing" in md.lower()
    # lint-clean with the benchmark-token note exempt via owner_spans (RF1)
    assert sg.HONEST_EVIDENCE_NOTE in r.owner_spans
    assert _BENCH.search(sg.HONEST_EVIDENCE_NOTE) is not None
    assert lint(r) == []
    golden("scout_review.md.txt", r.markdown)
    golden("scout_review.html.txt", r.telegram_html)


def test_both_skins_carry_every_symbol():
    r = render_scout_review(_ctx())
    for sym in ("MSFT", "FADS", "PEND"):
        assert sym in r.markdown and sym in r.telegram_html
    assert "```" in r.markdown and "<pre>" in r.telegram_html
