"""P5.11 — render_event: quiet-ack and data-lag (D.3 / §2.4).

The event report is NOT a push for a fired trigger (a FIRE is an Alert, §2.5). This
renderer covers the two non-firing outcomes:
  * quiet outcome — owner-initiated /event check that passed: one immediate calm
    acknowledgement, and a note that it also folds into tomorrow's daily letter;
  * data-lag — statements not yet updated post-earnings: retry note + a statement that
    the owner's prompted questions do not wait for the data.
Calm register throughout (no exclamation marks, no euro/P&L, no benchmark).
"""
from datetime import datetime, timezone

from agentcy.render.event import render_event
from agentcy.render.lint import lint
from agentcy.render.contexts import EventContext

GEN = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def _quiet():
    return EventContext(ticker="MSFT", event_kind="earnings", owner_initiated=True,
        triggers_pass=4, triggers_total=4, data_lag=False, retry_note=None,
        prompted_ask_ids=(), generated_at=GEN)


def _lag():
    return EventContext(ticker="CRWD", event_kind="earnings", owner_initiated=True,
        triggers_pass=0, triggers_total=3, data_lag=True,
        retry_note="statements not yet updated after earnings. I'll retry daily for 7 days.",
        prompted_ask_ids=("Q1041",), generated_at=GEN)


def test_quiet_ack(golden):
    r = render_event(_quiet())
    assert r.output_class == "event"
    assert "MSFT — earnings checked against your committed triggers." in r.telegram_html
    assert "4/4 pass. Thesis intact. No action needed." in r.telegram_html
    assert "one line in tomorrow's letter" in r.telegram_html
    assert lint(r) == []
    golden("event_quiet.html.txt", r.telegram_html)
    golden("event_quiet.md.txt", r.markdown)


def test_data_lag_states_retry_and_does_not_wait(golden):
    r = render_event(_lag())
    assert "retry daily for 7 days" in r.telegram_html
    assert "do not wait for the data" in r.telegram_html
    assert lint(r) == []
    golden("event_data_lag.html.txt", r.telegram_html)
    golden("event_data_lag.md.txt", r.markdown)
