from datetime import datetime, timezone

from agentcy.render.weekly import render_weekly
from agentcy.render.lint import lint
from agentcy.render.contexts import (WeeklyContext, PortfolioRow, DecisionBlock, StudyContext)

GEN = datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc)  # Saturday


def _study():
    return StudyContext("VEEV", "Vertical SaaS…", "Still deepening?",
                        "Inversion: what guarantees failure?", ("JE-0042 — bought DDOG.",),
                        "Reading queue: 2 reports.", "N112")


def _decision():
    import json
    km = json.dumps({"inline_keyboard": [[
        {"text": "Yes", "callback_data": "trig:yes:Q1041"},
        {"text": "No", "callback_data": "trig:no:Q1041"},
        {"text": "Can't verify", "callback_data": "trig:cant:Q1041"}]]})
    return DecisionBlock(ask_id="Q1041", heading="Prompted check — VEEV — T3",
                         body='Committed question: "Has the founder-CEO departed?"',
                         reply_markup_json=km)


def _row():
    return PortfolioRow("DDOG", 7.1, 42000.0, "framework", "intact", 2, "high",
                        "software", 24.0, 28.0, 36.0, "4/4 pass")


def _ctx(decisions=(), balance=None, clusters=None):
    from types import SimpleNamespace
    balance = balance or SimpleNamespace(cash_pct=8.1, cash_in_band=True,
        position_count_in_band=True, n_eff=5.2, n_eff_ok=True,
        soft_cap_breaches=(), hard_cap_breaches=(), cluster_weight_breaches=(),
        outside_framework_pct=6.0, outside_cap_ok=True, unpriced_weight_pct=1.2,
        n_framework=11, n_backfill=1, n_outside=2, leverage_violations=())
    clusters = clusters or SimpleNamespace(memberships={"DDOG": 0}, cluster_weights={0: 7.1},
        n_eff=5.2, corr_matrix=None, excluded=(), stale=False)
    return WeeklyContext(as_of=GEN,
        headline_verdict="No action needed." if not decisions else "2 decisions waiting.",
        celebrated=not decisions, decisions=tuple(decisions),
        portfolio=(_row(),), total_eur=420000.0,
        revalidations=("DDOG — thesis intact; 4/4 triggers pass.",),
        backfill_queue_line="Next in backfill queue: ASML.",
        broken_but_held=(), reaffirmations_due=("VEEV — annual re-affirmation due.",),
        balance=balance, clusters=clusters,
        dividend_lines=("MSFT — €120 received since last snapshot.",), reinvest_reminder=True,
        loosening_echoes=(), outside_framework_line="Outside framework: 6.0% (cap 10% ✓).",
        watchlist_lines=("SNOW — raw, 40 days to expiry.",),
        prompted_questions=tuple(decisions), study=_study(),
        data_health=("all sources fresh.",), generated_at=GEN)


def test_weekly_returns_series_and_document(golden):
    series, doc = render_weekly(_ctx(decisions=(_decision(),)))
    assert isinstance(series, tuple) and len(series) == 4
    assert series[0].output_class == "weekly_msg" and doc.output_class == "weekly_doc"
    # Msg 1 headline first
    assert series[0].telegram_html.startswith("<b>Weekly review — Sat 11 Jul 2026 — 1/4</b>")
    assert "full detail in the document that follows" in series[0].telegram_html
    # Msg 2 carries the decision keyboard (the ONLY weekly message with one)
    assert series[1].ask_id == "Q1041" and series[1].reply_markup_json is not None
    assert series[2].reply_markup_json is None and series[3].reply_markup_json is None
    # value lives weekly (§15 A3): doc carries EUR, but NO benchmark, NO cost basis
    assert "€420,000" in doc.markdown or "420,000" in doc.markdown
    assert "S&P" not in doc.telegram_html and "cost basis" not in doc.markdown.lower()
    for r in series + (doc,):
        assert lint(r) == []
    golden("weekly_full.msg1.html.txt", series[0].telegram_html)
    golden("weekly_full.msg1.md.txt", series[0].markdown)
    golden("weekly_full.msg2.html.txt", series[1].telegram_html)
    golden("weekly_full.msg3.html.txt", series[2].telegram_html)
    golden("weekly_full.msg4.html.txt", series[3].telegram_html)
    golden("weekly_full.doc.html.txt", doc.telegram_html)
    golden("weekly_full.doc.md.txt", doc.markdown)


def test_no_decisions_collapses_msg2(golden):
    series, doc = render_weekly(_ctx(decisions=()))
    assert "No decisions waiting." in series[1].telegram_html
    assert series[1].reply_markup_json is None
    golden("weekly_no_decisions.msg2.html.txt", series[1].telegram_html)
    golden("weekly_no_decisions.msg2.md.txt", series[1].markdown)
