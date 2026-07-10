"""Stage-1 tiered graded render (design §3): tier-sectioned, grade-sorted within each tier,
plus a cross-cutting 'Outside-tier A-grades' list, plus the honest evidence note. Two skins
from one context; lint-clean (output_class 'notice').

RF1 (blocking): the whole HONEST_EVIDENCE_NOTE paragraph rides in RenderedOutput.owner_spans
(it contains 'outperformance', a _BENCH benchmark token) so lint(r) == [] WITH the note in
owner_spans — the raw note is NEVER run through the template-span checks.
RF9: both skins are built from ONE context via cm.pre_table(rows, skin='md'/'html'); no dead
'if False' placeholder — the two goldens are structurally parallel.
"""
from agentcy.render.scout import ScoutGradedContext, render_scout_graded
from agentcy.render.lint import lint
from agentcy import scout_grade as sg


def _ctx():
    # GradedName field order (Stage-1.5): symbol, sector, tier, v, q, g, d, m, composite, grade, note
    graded = (
        sg.GradedName("VEEV", "Technology", "Core", 58.0, 92.0, 70.0, 84.0, 80.0, 78.0, "B", ""),
        sg.GradedName("MSFT", "Technology", "Core", 40.0, 88.0, 60.0, 90.0, 71.0, 71.0, "B", ""),
        sg.GradedName("DIST", "Industrials", "Outside", 90.0, 74.0, 65.0, 82.0, 83.0, 83.0, "A", ""),
        sg.GradedName("SWX", "Technology", "Adjacent", 55.0, 60.0, 55.0, 65.0, 60.0, 60.0, "C", ""),
        sg.GradedName("LEVR", "Technology", "Adjacent", None, None, None, None, None, None,
                      "VETOED", "leverage veto: net debt/EBITDA above the §2 floor"),
        sg.GradedName("THIN", "Technology", "Outside", None, None, None, None, None, None,
                      "INSUFFICIENT", "insufficient data: <2 usable periods"),
    )
    return ScoutGradedContext(as_of_label="Fri 10 Jul 2026", graded=graded,
                              evidence_note=sg.HONEST_EVIDENCE_NOTE)


def test_render_tiered_grade_sorted(golden):
    r = render_scout_graded(_ctx())
    assert r.output_class == "notice"
    md = r.markdown
    # tier sections present, in priority order
    assert md.index("Core") < md.index("Adjacent") < md.index("Outside")
    # within Core, higher composite (VEEV 78) sorts above MSFT 71
    assert md.index("VEEV") < md.index("MSFT")
    # Outside-tier A cross-list surfaces DIST (design §3 star)
    assert "Outside-tier A-grades" in md and "DIST" in md.split("Outside-tier A-grades")[1]
    # vetoed name is suppressed from the ranked lists but named as vetoed with a reason
    assert "LEVR" in md and "leverage veto" in md
    # insufficient-data name never shows a silent 0/grade
    assert "insufficient data" in md.lower()
    # honest evidence note printed every run
    assert "promises nothing" in md.lower()
    # lint-clean (no !, no benchmark/euro tokens)
    assert lint(r) == []
    golden("scout_graded.md.txt", r.markdown)
    golden("scout_graded.html.txt", r.telegram_html)


def test_evidence_note_rides_in_owner_spans_so_bench_token_is_exempt():
    """RF1 (blocking): the honest-evidence note contains 'outperformance' (a _BENCH token).
    It is exempted ONLY because the whole paragraph is an owner_span; without that exemption
    the lint would flag no_benchmark_token."""
    r = render_scout_graded(_ctx())
    # the whole note is the escape hatch — verbatim, in owner_spans
    assert sg.HONEST_EVIDENCE_NOTE in r.owner_spans
    # sanity: the note really would trip the lint if it were template text
    from agentcy.render.lint import _BENCH
    assert _BENCH.search(sg.HONEST_EVIDENCE_NOTE) is not None
    # yet, with the span exempted, the output is clean
    assert lint(r) == []


def test_both_skins_from_one_context_are_structurally_parallel():
    """RF9: md and html are built from the same row data — every graded/suppressed symbol
    that appears in one skin appears in the other."""
    r = render_scout_graded(_ctx())
    for sym in ("VEEV", "MSFT", "DIST", "SWX", "LEVR", "THIN"):
        assert sym in r.markdown, sym
        assert sym in r.telegram_html, sym
    # md uses a fenced monospace table; html uses a <pre> block (skin split, one context)
    assert "```" in r.markdown
    assert "<pre>" in r.telegram_html


def test_dilution_penalty_note_is_flagged_on_a_graded_row():
    """A graded (A/B/C/D/F) row carries the -15 dilution-penalty reason in GradedName.note;
    the design 2 table row requires that penalty be FLAGGED, not silently folded into the
    composite. The renderer already holds the reason (g.note) — it must surface it as a
    'flagged - {symbol}: {note}' line, in BOTH skins, for any ranked row with a non-empty note."""
    graded = (
        sg.GradedName("DILUT", "Technology", "Core", 60.0, 55.0, 65.0, 70.0, 30.0, 62.0,
                      "C", "dilution penalty: shares +14.0%/yr"),
    )
    ctx = ScoutGradedContext(as_of_label="Fri 10 Jul 2026", graded=graded,
                             evidence_note=sg.HONEST_EVIDENCE_NOTE)
    r = render_scout_graded(ctx)
    # the reason is surfaced, not silently dropped, in both skins
    assert "dilution penalty: shares +14.0%/yr" in r.markdown
    assert "dilution penalty: shares +14.0%/yr" in r.telegram_html
    assert "flagged - DILUT" in r.markdown
    assert "flagged - DILUT" in r.telegram_html
    # a clean graded row (empty note) emits no 'flagged' line
    clean = ScoutGradedContext(
        as_of_label="Fri 10 Jul 2026",
        graded=(sg.GradedName("CLEAN", "Technology", "Core", 60.0, 55.0, 65.0, 70.0, 55.0, 62.0, "C", ""),),
        evidence_note=sg.HONEST_EVIDENCE_NOTE)
    assert "flagged" not in render_scout_graded(clean).markdown
    # still lint-clean (calm register: no bang / benchmark / imperative tokens)
    assert lint(r) == []
