"""P6.9: D.2 Saturday refresh batch; D.3 detectors write event rows + atomic spool files (§1.5)."""
import json
from datetime import datetime, timezone

from agentcy import db, events, runlog
from agentcy.clock import FixedClock

SAT = FixedClock(datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc))


def _weekly_run_id(conn):
    """A real run_log parent so event.run_id (FK -> run_log) inserts cleanly, mirroring
    the sweep-supplied handle.run_id the P6.12 caller passes in production."""
    return runlog.start(conn, "weekly", "2026-07-11", clock=SAT).run_id


def _stub_fetch(monkeypatch, *, officers_changed=False, new_fps=None, shares_fail=False):
    from agentcy.fetch import store, yf
    from agentcy.fetch.yf import FetchFailed
    monkeypatch.setattr(yf, "fetch_daily_bars", lambda t, *, state_dir, period="10d": object())
    monkeypatch.setattr(yf, "fetch_statements", lambda t, *, state_dir: {"income": object()})
    monkeypatch.setattr(yf, "fetch_officers", lambda t, *, state_dir: [{"name": "S. Nadella"}])
    monkeypatch.setattr(yf, "fetch_calendar", lambda t, *, state_dir: "2026-07-24")
    if shares_fail:
        def _boom(t, *, state_dir):
            raise FetchFailed("empty series")
        monkeypatch.setattr(yf, "fetch_shares_full", _boom)
    else:
        monkeypatch.setattr(yf, "fetch_shares_full", lambda t, *, state_dir: object())
    monkeypatch.setattr(store, "store_price_bars", lambda conn, t, f, *, run_id, fetched_at: 1)
    monkeypatch.setattr(store, "store_statements",
                        lambda conn, t, s, *, run_id, fetched_at: list(new_fps or []))
    monkeypatch.setattr(store, "store_shares", lambda conn, t, s, *, fetched_at: 1)
    monkeypatch.setattr(store, "store_officers",
                        lambda conn, t, o, *, fetched_at: officers_changed)
    monkeypatch.setattr(store, "store_calendar",
                        lambda conn, t, d, *, run_id, fetched_at: None)


def _seed_baseline(conn):
    db.append_fundamentals_period(conn, yf_ticker="MSFT", statement_type="income",
                                  period_end="2026-03-31", payload_json="{}",
                                  fingerprint="base", fetched_at="2026-07-04T06:00:00Z", run_id=None)


def test_new_fingerprint_with_baseline_spools_earnings_event(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _seed_baseline(conn)
    _stub_fetch(monkeypatch, new_fps=["fp-new"])
    weekly.refresh_batch(conn, run_id=_weekly_run_id(conn), clock=SAT, state_dir=tmp_path)
    evs = db.fetch_events_for(conn, "MSFT")
    assert any(e["source"] == "fingerprint" and e["kind"] == "earnings" for e in evs)
    paths = events.spool_paths(tmp_path)
    assert len(paths) == 1
    assert json.loads(paths[0].read_text(encoding="utf-8"))["source"] == "fingerprint"


def test_first_ever_fetch_does_not_spool(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]     # NO baseline row
    _stub_fetch(monkeypatch, new_fps=["fp-1", "fp-2"])
    weekly.refresh_batch(conn, run_id=1, clock=SAT, state_dir=tmp_path)
    assert db.fetch_events_for(conn, "MSFT") == []      # bootstrap fill, not an earnings event
    assert events.spool_paths(tmp_path) == []


def test_officer_diff_spools_mgmt_event(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _stub_fetch(monkeypatch, officers_changed=True)
    weekly.refresh_batch(conn, run_id=_weekly_run_id(conn), clock=SAT, state_dir=tmp_path)
    evs = db.fetch_events_for(conn, "MSFT")
    assert any(e["source"] == "officer_diff" and e["kind"] == "mgmt" for e in evs)


def test_fetch_failure_degrades_that_step_and_continues(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _stub_fetch(monkeypatch, shares_fail=True)
    out = weekly.refresh_batch(conn, run_id=1, clock=SAT, state_dir=tmp_path)
    assert any("MSFT" in l and "shares" in l for l in out["data_health"])   # suspended stated
