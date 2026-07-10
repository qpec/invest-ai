"""P6.8: Sun/Mon two-line pulse (S0), daily_letter_mode=quiet (D.6), dead-man ping (S2), gap line."""
from datetime import datetime, timedelta, timezone

from agentcy import config as config_mod
from agentcy import db
from agentcy.clock import FixedClock


SUNDAY = FixedClock(datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc))   # Sun 07:00 Amsterdam


def test_pulse_day_skips_fetch_and_sends_two_liner(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import daily, runner
    conn = seeded_portfolio["conn"]

    def _no_fetch(*a, **k):
        raise AssertionError("pulse day must not touch Yahoo")
    monkeypatch.setattr(daily, "refresh_prices", _no_fetch)
    rc = runner.sweep_and_run(conn, "daily", daily.run_one, clock=SUNDAY, state_dir=tmp_path)
    assert rc == 0
    # every daily key due since the fixed_clock epoch is swept; the Sunday one is the pulse:
    ob = db.fetch_outbox_by_key(conn, "daily:2026-07-12:letter")
    assert ob is not None
    run = db.fetch_run(conn, "daily", "2026-07-12")
    import json
    assert json.loads(run["outputs_json"])["kind"] == "pulse"


def _finish_prior_daily_keys(conn, clock, keep):
    """Steady state: every earlier due day already ran on time, so the sweep has exactly one
    on-time key today (mirrors test_jobs_daily.py) — otherwise the 14-day lookback archives 14."""
    from agentcy import runlog
    for key in runlog.due_keys("daily", as_of=clock.now()):
        if key == keep:
            continue
        h = runlog.start(conn, "daily", key, clock=clock)
        runlog.finish(conn, h.run_id, status="ok", outputs={"kind": "pulse"}, clock=clock)


def test_quiet_mode_suppresses_letter_but_still_runs_and_archives(seeded_portfolio, fixed_clock,
                                                                  tmp_path, monkeypatch):
    from agentcy import journal
    from agentcy.journal import EntryIn
    from agentcy.jobs import daily, runner
    conn = seeded_portfolio["conn"]
    _finish_prior_daily_keys(conn, fixed_clock, keep="2026-07-08")
    config_mod.set(conn, "daily_letter_mode", "quiet", reason="vacation", actor="owner", clock=fixed_clock)
    je = journal.append(conn, EntryIn(decision_type="config_or_designation",
                                      decision_subtype="config_change",
                                      reasoning_at_the_moment="pause on", actor="owner"), clock=fixed_clock)
    db.append_absence_event(conn, kind="on", at=db.to_iso(fixed_clock.now() - timedelta(days=1)),
                            journal_ref=je)
    conn.commit()
    monkeypatch.setattr(daily, "refresh_prices",
                        lambda conn, tickers, **kw: {"MSFT": "ok", "USDEUR=X": "ok"})
    runner.sweep_and_run(conn, "daily", daily.run_one, clock=fixed_clock, state_dir=tmp_path)
    assert db.fetch_run(conn, "daily", "2026-07-08")["status"] == "ok"     # runs still execute (D.6)
    assert len(db.fetch_reports(conn, type="daily")) == 1                  # archive still written
    assert db.fetch_outbox_by_key(conn, "daily:2026-07-08:letter") is None # delivery suppressed


def test_deadman_ping_gets_url_and_skips_when_unset(tmp_db, monkeypatch):
    from agentcy import deadman
    # set-time must fall AFTER the deadman_ping_url seed's valid_from (2026-07-09, S2 install)
    # so the owner's URL supersedes the empty default (config is latest-valid_from-wins):
    install = FixedClock(datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc))
    monkeypatch.delenv("AGENTCY_DEADMAN_URL", raising=False)
    calls = []
    monkeypatch.setattr(deadman.urllib.request, "urlopen",
                        lambda url, timeout=10: calls.append(url) or type("R", (), {"close": lambda s: None})())
    deadman.ping(tmp_db)                              # seeded '' -> no call, no network
    assert calls == []
    config_mod.set(tmp_db, "deadman_ping_url", "https://hc-ping.example/abc",
                   reason="S2 install", actor="owner", clock=install)
    deadman.ping(tmp_db)
    assert calls == ["https://hc-ping.example/abc"]


def test_gap_line_names_missed_days_on_catchup(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import daily, runner
    conn = seeded_portfolio["conn"]
    monkeypatch.setattr(daily, "refresh_prices",
                        lambda conn, tickers, **kw: {"MSFT": "ok", "USDEUR=X": "ok"})
    friday = FixedClock(datetime(2026, 7, 10, 5, 0, tzinfo=timezone.utc))
    runner.sweep_and_run(conn, "daily", daily.run_one, clock=friday, state_dir=tmp_path)
    # the newest (on-time) letter names the gap; earlier keys ran late
    assert db.fetch_run(conn, "daily", "2026-07-08")["late"] == 1
    ob = db.fetch_outbox_by_key(conn, "daily:2026-07-10:letter")
    assert ob is not None and "no letters were sent" in ob["payload_html"]
