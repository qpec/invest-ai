"""P6.7: MA-7 'calendar estimate' preview + quiet-outcome fold-in + 7-day lag re-spool (D.3)."""
import json
from datetime import timedelta

from agentcy import db, events, runlog
from agentcy.clock import FixedClock


def test_events_line_earnings_preview_labeled_calendar_estimate(seeded_portfolio, fixed_clock, monkeypatch):
    from agentcy.fetch import store
    from agentcy.jobs import daily
    conn = seeded_portfolio["conn"]
    monkeypatch.setattr(store, "next_expected_earnings",
                        lambda c, t, *, as_of: "2026-07-24" if t == "MSFT" else None)
    line = daily.events_line(conn, as_of=fixed_clock.now())
    assert line is not None
    assert "MSFT" in line and "calendar estimate" in line and "16 days" in line  # MA-7 label mandatory


def test_events_line_folds_quiet_outcome(seeded_portfolio, fixed_clock, monkeypatch):
    from agentcy.fetch import store
    from agentcy.jobs import daily
    conn = seeded_portfolio["conn"]
    monkeypatch.setattr(store, "next_expected_earnings", lambda c, t, *, as_of: None)
    detected = db.to_iso(fixed_clock.now() - timedelta(hours=20))
    db.append_event(conn, dict(yf_ticker="MSFT", source="fingerprint", kind="earnings",
                               note=None, detected_at=detected, detected_late=0, run_id=None))
    clk = FixedClock(fixed_clock.now() - timedelta(hours=19))
    rh = runlog.start(conn, "event", f"MSFT:{detected}", clock=clk)
    runlog.finish(conn, rh.run_id, status="ok",
                  outputs={"quiet": True, "triggers_pass": "2/2", "data_lag": False}, clock=clk)
    conn.commit()
    line = daily.events_line(conn, as_of=fixed_clock.now())
    assert "MSFT earnings checked" in line and "2/2" in line and "no action needed" in line


def test_respool_lagging_event_daily_for_seven_days(seeded_portfolio, fixed_clock, tmp_path):
    from agentcy.jobs import daily
    conn = seeded_portfolio["conn"]
    detected = db.to_iso(fixed_clock.now() - timedelta(days=2))
    eid = db.append_event(conn, dict(yf_ticker="MSFT", source="owner", kind="earnings",
                                     note="q2", detected_at=detected, detected_late=0, run_id=None))
    clk = FixedClock(fixed_clock.now() - timedelta(days=2))
    rh = runlog.start(conn, "event", f"MSFT:{detected}", clock=clk)
    runlog.finish(conn, rh.run_id, status="degraded",
                  outputs={"quiet": True, "data_lag": True, "event_id": eid}, clock=clk)
    conn.commit()
    n = daily.respool_lagging_events(conn, as_of=fixed_clock.now(), state_dir=tmp_path)
    assert n == 1
    paths = events.spool_paths(tmp_path)
    assert len(paths) == 1
    req = json.loads(paths[0].read_text(encoding="utf-8"))
    assert req["yf_ticker"] == "MSFT" and req["source"] == "owner"   # attributed to original source
    # beyond 7 days: no re-spool
    old = FixedClock(fixed_clock.now() + timedelta(days=9))
    assert daily.respool_lagging_events(conn, as_of=old.now(), state_dir=tmp_path) == 0
