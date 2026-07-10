"""P6.6: deadline consequences (alert_ignored / UNVERIFIABLE) + open loops head the letter (B.3.3)."""
from datetime import timedelta

from agentcy import db, runlog
from agentcy.clock import FixedClock
from agentcy.freshness import CheckResult
from agentcy.triggers import CheckOutcome


def _fire_alert(conn, seeded, when):
    """Fire the seeded margin trigger at `when` via the real P3 path; returns (alert_id, ask_id)."""
    from agentcy import triggers
    clk = FixedClock(when)
    rh = runlog.start(conn, "weekly", "seed-fire", clock=clk)
    trig = db.fetch_armed_triggers(conn, seeded["thesis_id"])[0]
    outcome = CheckOutcome(trigger_id=trig["trigger_id"], result=CheckResult.FIRE,
                           observed_value=17.1, headroom=-2.9, evaluable_from=None, note="2q slide")
    alert_id = triggers.fire(conn, outcome, clock=clk, run_id=rh.run_id)
    ask = [a for a in db.fetch_open_asks(conn, kind="A") if a["alert_ref"] == alert_id][0]
    conn.commit()
    return alert_id, ask["ask_id"]


def test_past_deadline_alert_journals_alert_ignored_once(seeded_portfolio, fixed_clock):
    from agentcy.jobs import daily
    conn = seeded_portfolio["conn"]
    ten_days_ago = fixed_clock.now() - timedelta(days=10)     # deadline (+7d) already passed
    alert_id, ask_id = _fire_alert(conn, seeded_portfolio, ten_days_ago)
    rh = runlog.start(conn, "daily", "loops-test", clock=fixed_clock)
    daily.sweep_ask_deadlines(conn, clock=fixed_clock, run_id=rh.run_id)
    entries = db.fetch_journal_entries(conn, decision_type="alert_ignored")
    assert len(entries) == 1 and entries[0]["ask_ref"] == ask_id
    assert db.fetch_ask(conn, ask_id)["status"] == "unanswered"
    # idempotent: a second daily run must not journal twice
    daily.sweep_ask_deadlines(conn, clock=fixed_clock, run_id=rh.run_id)
    assert len(db.fetch_journal_entries(conn, decision_type="alert_ignored")) == 1


def test_ignored_alert_heads_open_loops(seeded_portfolio, fixed_clock):
    from agentcy.jobs import daily
    conn = seeded_portfolio["conn"]
    alert_id, ask_id = _fire_alert(conn, seeded_portfolio, fixed_clock.now() - timedelta(days=10))
    rh = runlog.start(conn, "daily", "loops-test-2", clock=fixed_clock)
    daily.sweep_ask_deadlines(conn, clock=fixed_clock, run_id=rh.run_id)
    loops = daily.open_loop_lines(conn, as_of=fixed_clock.now())
    assert loops and loops[0].ask_id == ask_id                # alert_ignored heads the letter (B.3.3)
    assert "ALERT IGNORED" in loops[0].label
    assert loops[0].age_days == 10


def test_unanswered_prompted_question_records_unverifiable(seeded_portfolio, fixed_clock):
    from agentcy import asks
    from agentcy.jobs import daily
    conn = seeded_portfolio["conn"]
    prompted = [t for t in db.fetch_armed_triggers(conn, seeded_portfolio["thesis_id"])
                if t["check_method"] == "prompted"][0]
    old = FixedClock(fixed_clock.now() - timedelta(days=10))
    ask = asks.mint(conn, kind="Q", prompt="Has the CEO departed?", options=["yes", "no", "cant"],
                    thesis_ref=seeded_portfolio["thesis_id"], trigger_ref=prompted["trigger_id"],
                    deadline=db.to_iso(old.now() + timedelta(days=7)), clock=old)
    conn.commit()
    rh = runlog.start(conn, "daily", "loops-test-3", clock=fixed_clock)
    daily.sweep_ask_deadlines(conn, clock=fixed_clock, run_id=rh.run_id)
    check = db.fetch_latest_trigger_check(conn, prompted["trigger_id"])
    assert check is not None and check["result"] == "UNVERIFIABLE"   # B.3.4: never green
