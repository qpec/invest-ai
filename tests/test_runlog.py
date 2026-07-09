"""RunLog logical keys and the per-run_type flock (contracts §3.5, tech-arch §1.3)."""
from __future__ import annotations

import json

import pytest

from agentcy import db, runlog


def test_start_inserts_with_effective_config_pinned(tmp_db, fixed_clock):
    h = runlog.start(tmp_db, "daily", "2026-07-08", clock=fixed_clock)
    assert (h.run_type, h.scheduled_for, h.late) == ("daily", "2026-07-08", False)
    row = db.fetch_run(tmp_db, "daily", "2026-07-08")
    assert row["attempt"] == 1 and row["finished_at"] is None
    inputs = json.loads(row["inputs_json"])
    assert inputs["config"]["cash_band_low_pct"] == "5"      # §9: defaults auditable forever


def test_finish_and_is_finished(tmp_db, fixed_clock):
    h = runlog.start(tmp_db, "daily", "2026-07-08", clock=fixed_clock)
    assert not runlog.is_finished(tmp_db, "daily", "2026-07-08")
    runlog.finish(tmp_db, h.run_id, status="ok", outputs={"letter": 1},
                  clock=fixed_clock)
    assert runlog.is_finished(tmp_db, "daily", "2026-07-08")
    row = db.fetch_run(tmp_db, "daily", "2026-07-08")
    assert row["status"] == "ok" and json.loads(row["outputs_json"]) == {"letter": 1}


def test_restart_unfinished_key_reclaims_with_attempt_bump(tmp_db, fixed_clock):
    h1 = runlog.start(tmp_db, "daily", "2026-07-08", clock=fixed_clock)
    h2 = runlog.start(tmp_db, "daily", "2026-07-08", clock=fixed_clock, late=True)
    assert h2.run_id == h1.run_id and h2.late is True
    assert db.fetch_run(tmp_db, "daily", "2026-07-08")["attempt"] == 2


def test_start_on_finished_key_raises(tmp_db, fixed_clock):
    h = runlog.start(tmp_db, "daily", "2026-07-08", clock=fixed_clock)
    runlog.finish(tmp_db, h.run_id, status="ok", outputs={}, clock=fixed_clock)
    with pytest.raises(RuntimeError, match="finished"):
        runlog.start(tmp_db, "daily", "2026-07-08", clock=fixed_clock)


def test_event_keys_are_object_identities_not_dates(tmp_db, fixed_clock):
    # §1.3: several event checks one Saturday never collide on UNIQUE(run_type, scheduled_for)
    runlog.start(tmp_db, "event", "MSFT:2026-07-08T05:00:00Z", clock=fixed_clock)
    runlog.start(tmp_db, "event", "ASML.AS:2026-07-08T05:00:00Z", clock=fixed_clock)
    assert db.fetch_run(tmp_db, "event", "MSFT:2026-07-08T05:00:00Z") is not None


def test_run_lock_is_exclusive(tmp_path):
    assert not runlog._lock_held(tmp_path, "daily")
    with runlog.run_lock(tmp_path, "daily"):
        assert runlog._lock_held(tmp_path, "daily")
        assert not runlog._lock_held(tmp_path, "weekly")   # per-run_type, not global
    assert not runlog._lock_held(tmp_path, "daily")
    assert (tmp_path / "locks" / "daily.lock").exists()    # stale file is harmless (fd-scoped)


from datetime import datetime, timedelta, timezone

AS_OF = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)   # 07:00 Europe/Amsterdam, a Wednesday


def test_due_keys_daily_includes_today_after_fire_time():
    keys = runlog.due_keys("daily", as_of=AS_OF)
    assert len(keys) == 14 and keys == sorted(keys)
    assert keys[-1] == "2026-07-08"                        # 07:00 fire time just reached
    assert keys[0] == "2026-06-25"


def test_due_keys_daily_excludes_today_before_fire_time():
    keys = runlog.due_keys("daily", as_of=AS_OF - timedelta(hours=1))  # 06:00 Amsterdam
    assert keys[-1] == "2026-07-07"


def test_due_keys_weekly_saturdays():
    assert runlog.due_keys("weekly", as_of=AS_OF) == [
        "2026-05-30", "2026-06-06", "2026-06-13", "2026-06-20",
        "2026-06-27", "2026-07-04"]


def test_due_keys_quarterly_and_backup_and_others():
    assert runlog.due_keys("quarterly", as_of=AS_OF) == ["2026-04-01", "2026-07-01"]
    assert runlog.due_keys("backup", as_of=AS_OF)[-1] == "2026-07-08"   # 03:30 passed
    assert runlog.due_keys("event", as_of=AS_OF) == []                  # object-identity keys
    assert runlog.due_keys("gate", as_of=AS_OF) == []


def test_sweepable_absent_finished_running_crashed(tmp_db, tmp_path, fixed_clock):
    timeout = timedelta(minutes=30)
    # absent keys are sweepable
    assert "2026-07-08" in runlog.sweepable(tmp_db, "daily", as_of=AS_OF,
                                            timeout=timeout, state_dir=tmp_path)
    # finished key: not sweepable
    h = runlog.start(tmp_db, "daily", "2026-07-08", clock=fixed_clock)
    runlog.finish(tmp_db, h.run_id, status="ok", outputs={}, clock=fixed_clock)
    assert "2026-07-08" not in runlog.sweepable(tmp_db, "daily", as_of=AS_OF,
                                                timeout=timeout, state_dir=tmp_path)
    # started recently (within timeout): not sweepable — may still be running
    runlog.start(tmp_db, "daily", "2026-07-07", clock=fixed_clock)
    assert "2026-07-07" not in runlog.sweepable(tmp_db, "daily", as_of=AS_OF,
                                                timeout=timeout, state_dir=tmp_path)
    # started long ago and unlocked: crashed -> sweepable
    from agentcy.clock import FixedClock
    stale_clock = FixedClock(AS_OF - timedelta(hours=3))
    runlog.start(tmp_db, "daily", "2026-07-06", clock=stale_clock)
    assert "2026-07-06" in runlog.sweepable(tmp_db, "daily", as_of=AS_OF,
                                            timeout=timeout, state_dir=tmp_path)
    # ...but not while the run_type lock is held: running, not crashed
    with runlog.run_lock(tmp_path, "daily"):
        assert "2026-07-06" not in runlog.sweepable(tmp_db, "daily", as_of=AS_OF,
                                                    timeout=timeout, state_dir=tmp_path)


def test_report_missing_detects_and_reports_only(tmp_db, fixed_clock):
    missing = runlog.report_missing(tmp_db, as_of=AS_OF)
    assert "daily:2026-07-08" in missing
    assert "weekly:2026-07-04" in missing
    assert "quarterly:2026-07-01" in missing
    h = runlog.start(tmp_db, "daily", "2026-07-08", clock=fixed_clock)
    runlog.finish(tmp_db, h.run_id, status="ok", outputs={}, clock=fixed_clock)
    assert "daily:2026-07-08" not in runlog.report_missing(tmp_db, as_of=AS_OF)
    # detect-and-report only: no run_log rows were created by the sweep itself
    assert tmp_db.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 1
