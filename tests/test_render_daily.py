from datetime import datetime, timezone

from agentcy.render.daily import render_daily, render_status
from agentcy.render.lint import lint
from agentcy.render.contexts import (DailyContext, HeaderBlock, OpportunityLine,
                                     OpenLoopLine, StatusContext)

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


AS_OF2 = datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc)  # Sunday


def _pulse():
    return DailyContext(kind="pulse", as_of=AS_OF2, header=None,
        verdict_line="markets closed — nothing to check.",
        opportunities=(), more_opportunities=0, events_line=None,
        data_lines=("data health ✓",), open_loops=(), open_items_count=3,
        generated_at=AS_OF2, late_banner=None)


def _degraded():
    return DailyContext(kind="degraded", as_of=AS_OF2, header=None,
        verdict_line="Checks suspended — prices stale since Thu 3 Jul.",
        opportunities=(), more_opportunities=0, events_line=None,
        data_lines=("Last known: positions as of Sun 6 Jul. The letter resumes full checks when data returns.",),
        open_loops=(), open_items_count=0, generated_at=AS_OF2, late_banner=None)


def _total_failure():
    return DailyContext(kind="total_failure", as_of=AS_OF2, header=None,
        verdict_line="", opportunities=(), more_opportunities=0, events_line=None,
        data_lines=(), open_loops=(), open_items_count=0, generated_at=AS_OF2, late_banner=None)


def _holiday():   # holiday pulse: fetch succeeded, no new bar (NOT an outage)
    return DailyContext(kind="pulse", as_of=AS_OF2, header=None,
        verdict_line="US markets closed Fri 3 Jul (holiday) — nothing to check.",
        opportunities=(), more_opportunities=0, events_line=None,
        data_lines=("data health ✓",), open_loops=(), open_items_count=0,
        generated_at=AS_OF2, late_banner=None)


def _catchup():
    c = _pulse()
    return DailyContext(**{**c.__dict__,
        "kind": "full", "header": None,   # header injected by real job; test the gap+banner text
        "late_banner": "generated 2026-07-08 07:00 — delivered 2026-07-10 09:12"})


def test_pulse_is_two_lines_and_calm(golden):
    r = render_daily(_pulse())
    assert "markets closed" in r.telegram_html and lint(r) == []
    golden("daily_weekend_pulse.html.txt", r.telegram_html)
    golden("daily_weekend_pulse.md.txt", r.markdown)


def test_degraded_carries_verbatim_line(golden):
    r = render_daily(_degraded())
    assert "Nothing is wrong; I just can't see." in r.telegram_html and lint(r) == []
    golden("daily_degraded.html.txt", r.telegram_html)
    golden("daily_degraded.md.txt", r.markdown)


def test_total_failure_always_sends(golden):
    r = render_daily(_total_failure())
    assert "no checks performed" in r.telegram_html
    assert "Nothing is wrong; I just can't see." in r.telegram_html
    golden("daily_total_failure.html.txt", r.telegram_html)
    golden("daily_total_failure.md.txt", r.markdown)


def test_holiday_names_the_closed_market_not_an_outage(golden):
    r = render_daily(_holiday())
    assert "holiday" in r.telegram_html and "can't see" not in r.telegram_html
    golden("daily_holiday_vs_outage.html.txt", r.telegram_html)
    golden("daily_holiday_vs_outage.md.txt", r.markdown)


def test_late_banner_prepended(golden):
    r = render_daily(_catchup())
    assert r.telegram_html.startswith("generated 2026-07-08 07:00 — delivered")
    golden("daily_catchup_morning.html.txt", r.telegram_html)
    golden("daily_catchup_morning.md.txt", r.markdown)


def test_pause_mode_letter(golden):
    from agentcy.render.contexts import HeaderBlock
    h = HeaderBlock("Tue 8 Jul 2026", "manual export of Sun 6 Jul (2 days old)",
                    "fresh (07:00 CET)", 8.1, 5.0, 15.0, True, 11, 1, 2)
    ctx = DailyContext(kind="full", as_of=AS_OF2, header=h,
        verdict_line="No triggers fired. All theses intact. Doing nothing is today's best move.",
        opportunities=(), more_opportunities=0, events_line=None,
        data_lines=("Pause mode active — deadlines and skip counters frozen until 2026-07-22.",
                    "all sources fresh."),
        open_loops=(), open_items_count=0, generated_at=AS_OF2, late_banner=None)
    r = render_daily(ctx)
    assert "Pause mode active" in r.telegram_html and lint(r) == []
    golden("pause_mode_letter.html.txt", r.telegram_html)
    golden("pause_mode_letter.md.txt", r.markdown)


# --- P5.8: /status card ---------------------------------------------------------


def _status(open_loops=()):
    h = HeaderBlock("Tue 8 Jul 2026", "manual export of Sun 6 Jul (2 days old)",
                    "fresh (07:00 CET)", 8.1, 5.0, 15.0, True, 11, 1, 2)
    return StatusContext(now_label="Tue 8 Jul 2026, 14:12 CET", header=h,
        verdict_line="All theses intact. No triggers fired. No open decisions.",
        open_loops=open_loops,
        next_scheduled_line="Next scheduled: daily letter after tonight's US close.")


def test_status_card_calm(golden):
    r = render_status(_status())
    assert r.output_class == "status" and r.ask_id is None
    assert r.telegram_html.startswith("<b>Status — Tue 8 Jul 2026, 14:12 CET</b>")
    assert lint(r) == []
    golden("status_card.html.txt", r.telegram_html)
    golden("status_card.md.txt", r.markdown)


def test_status_with_open_loop_carries_ask_id():
    r = render_status(_status(open_loops=(OpenLoopLine("A238", "CRWD alert unanswered", 3),)))
    assert r.ask_id == "A238" and "A238" in r.telegram_html
