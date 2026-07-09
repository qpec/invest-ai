from datetime import datetime, timezone

from agentcy.render.daily import render_daily
from agentcy.render.lint import lint
from agentcy.render.contexts import DailyContext, HeaderBlock, OpportunityLine, OpenLoopLine

AS_OF = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def _header():
    return HeaderBlock(
        date_label="Tue 8 Jul 2026",
        snapshot_line="manual export of Sun 6 Jul (2 days old)",
        prices_line="fresh (07:00 CET)",
        cash_pct=8.1, cash_band_low=5.0, cash_band_high=15.0, cash_in_band=True,
        n_framework=11, n_backfill=1, n_outside=2)


def _all_clear():
    return DailyContext(
        kind="full", as_of=AS_OF, header=_header(),
        verdict_line="No triggers fired. All theses intact. Doing nothing is today's best move.",
        opportunities=(), more_opportunities=0,
        events_line="MSFT earnings expected 24 Jul (16 days, calendar estimate) — event check will run automatically on detection.",
        data_lines=("all sources fresh.",),
        open_loops=(), open_items_count=0, generated_at=AS_OF, late_banner=None)


def _opportunity():
    return DailyContext(
        kind="full", as_of=AS_OF, header=_header(),
        verdict_line="No triggers fired. All theses intact. Doing nothing is today's best move.",
        opportunities=(OpportunityLine(ticker="DDOG", multiple=24.0, band_low=28.0, band_high=36.0,
                                       thesis_version=2, triggers_pass=4, triggers_total=4,
                                       kind="on_sale", suspended_note=None),),
        more_opportunities=0,
        events_line=None, data_lines=("all sources fresh.",),
        open_loops=(), open_items_count=0, generated_at=AS_OF, late_banner=None)


def test_all_clear_headline_and_calm(golden):
    r = render_daily(_all_clear())
    assert r.output_class == "daily" and r.ask_id is None and r.reply_markup_json is None
    assert r.telegram_html.startswith("<b>Daily letter — Tue 8 Jul 2026 — ✓ No action needed</b>")
    assert lint(r) == []
    golden("daily_all_clear.html.txt", r.telegram_html)
    golden("daily_all_clear.md.txt", r.markdown)


def test_opportunity_carries_on_sale_and_invitation(golden):
    r = render_daily(_opportunity())
    assert "ON SALE" in r.telegram_html
    assert "this is an invitation, not an instruction." in r.telegram_html
    assert "24× P/FCF vs your fair band 28–36×" in r.telegram_html
    assert lint(r) == []
    golden("daily_opportunity.html.txt", r.telegram_html)
    golden("daily_opportunity.md.txt", r.markdown)


def test_no_euro_no_value_no_benchmark_in_daily():
    r = render_daily(_opportunity())
    assert "€" not in r.telegram_html and "S&P" not in r.telegram_html
