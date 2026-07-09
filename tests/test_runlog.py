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
