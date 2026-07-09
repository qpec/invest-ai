# tests/test_render_quarterly.py
from datetime import datetime, timezone
from agentcy.render.quarterly import render_quarterly
from agentcy.render.lint import lint
from agentcy.render.contexts import QuarterlyContext
GEN = datetime(2026, 7, 1, 6, 30, tzinfo=timezone.utc)


def _ctx():
    return QuarterlyContext(
        period="Q2 2026",
        honest_question={"since_inception_portfolio_pct": 14.2, "since_inception_benchmark_pct": 11.8,
                         "ttm_portfolio_pct": 9.1, "ttm_benchmark_pct": 10.4,
                         "quarter_portfolio_pct": 2.1, "quarter_benchmark_pct": 1.9},
        honest_answer_sentence="Since inception the process is ahead of the index; the trailing year is behind, and one quarter proves nothing.",
        caveats=("Flows approximated from owner-confirmed deposits.", "Unpriced weight 1.2%.",
                 "quantstats figures are indicative."),
        drawdown_context=("Mar trough coincided with the DDOG on-sale line you saw.",),
        process_review={"followed_good": ["JE-0042 DDOG buy — thesis intact."], "followed_bad": [],
                        "deviated_good": [], "deviated_bad": ["JE-0051 sold on a price scare."],
                        "followed_pct": 82.0, "override_hit_rate": "1/3",
                        "alert_ignored": ["A210 — CRWD, resolved late."], "no_action_ratio": "88%"},
        framework_audit={"gate_throughput": ["2 passed, 1 watch, 3 rejected"],
                         "trigger_relaxations": ["DDOG T1 loosened; headroom 4.2 pts."],
                         "config_changes": ["cash_band_high 15% (unchanged)."]},
        records_appendix={"rows": [{"ticker": "DDOG", "cost_basis_eur": 30000.0,
                                    "realized_gain_eur": 0.0, "trade_fx_note": "USD@0.92"}]},
        verdict_and_exit_clause="Process intact; keep judging process, not price.",
        generated_at=GEN)


def test_summary_carries_the_honest_question_and_answer(golden):
    summary, doc = render_quarterly(_ctx())
    assert summary.output_class == "quarterly_msg" and doc.output_class == "quarterly_doc"
    # summary: honest question + answer + standing reminder; benchmark IS allowed in quarterly
    # classes. The HTML skin escapes the ampersand (parse_mode=HTML, locked — same convention
    # the weekly renderer uses); the markdown skin keeps the benchmark token raw.
    assert "S&amp;P 500 TR (EUR)" in summary.telegram_html
    assert "S&P 500 TR (EUR)" in summary.markdown
    assert "The 10-year answer is the real one." in summary.telegram_html
    # summary carries NO cost basis, NO keyboard
    assert "cost basis" not in summary.telegram_html.lower() and summary.reply_markup_json is None
    assert lint(summary) == []
    golden("quarterly_summary_and_doc.summary.html.txt", summary.telegram_html)
    golden("quarterly_summary_and_doc.summary.md.txt", summary.markdown)


def test_document_is_the_ONLY_place_cost_basis_appears(golden):
    summary, doc = render_quarterly(_ctx())
    assert "cost basis" in doc.markdown.lower() or "Cost basis" in doc.markdown
    assert "DDOG" in doc.markdown and "30,000" in doc.markdown
    # indexing exit clause verbatim present (lint requires it in quarterly_doc)
    assert "the honest conclusion changes to indexing" in doc.markdown
    assert lint(doc) == []
    golden("quarterly_summary_and_doc.doc.html.txt", doc.telegram_html)
    golden("quarterly_summary_and_doc.doc.md.txt", doc.markdown)
