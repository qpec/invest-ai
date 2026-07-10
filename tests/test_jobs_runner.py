"""P6.2: run_type-scoped due-run sweep — per-type lock, late re-claims, finished keys exit 0 (§1.3)."""
from datetime import timedelta

from agentcy import db, runlog
from agentcy.clock import FixedClock


def _recorder(calls, status="ok"):
    def job(conn, handle, *, clock, state_dir):
        calls.append((handle.scheduled_for, handle.late))
        return status, {"ran": True}
    return job


def test_sweep_runs_due_key_and_finished_keys_exit_zero(tmp_db, fixed_clock, tmp_path):
    from agentcy.jobs import runner
    calls = []
    rc = runner.sweep_and_run(tmp_db, "daily", _recorder(calls), clock=fixed_clock, state_dir=tmp_path)
    assert rc == 0
    assert ("2026-07-08", False) in calls               # today's key, on time
    row = db.fetch_run(tmp_db, "daily", "2026-07-08")
    assert row["status"] == "ok" and row["finished_at"] is not None
    calls.clear()
    assert runner.sweep_and_run(tmp_db, "daily", _recorder(calls), clock=fixed_clock, state_dir=tmp_path) == 0
    assert calls == []                                  # re-fired finished key: exit 0, no re-run


def test_sweep_reclaims_crashed_key_marked_late(tmp_db, fixed_clock, tmp_path):
    from agentcy.jobs import runner
    yesterday = FixedClock(fixed_clock.now() - timedelta(days=1))
    runlog.start(tmp_db, "daily", "2026-07-07", clock=yesterday)   # started, never finished, stale > timeout
    tmp_db.commit()
    calls = []
    runner.sweep_and_run(tmp_db, "daily", _recorder(calls), clock=fixed_clock, state_dir=tmp_path)
    assert ("2026-07-07", True) in calls                # crashed key re-claimed, marked late
    assert db.fetch_run(tmp_db, "daily", "2026-07-07")["late"] == 1
    assert db.fetch_run(tmp_db, "daily", "2026-07-07")["status"] == "ok"


def test_qualified_key_attempt_suffix_only_after_sent(tmp_db, fixed_clock):
    from agentcy.jobs import runner
    from agentcy.tg import outbox
    base = "daily:2026-07-08:letter"
    assert runner.qualified_key(tmp_db, base) == base                     # no row yet
    oid = outbox.enqueue(tmp_db, dedupe_key=base, kind="daily", payload_html="x", clock=fixed_clock)
    assert runner.qualified_key(tmp_db, base) == base                     # queued -> supersede path
    db.update_outbox_state(tmp_db, oid, status="sent", tg_message_id=1)
    assert runner.qualified_key(tmp_db, base) == base + "#a2"             # sent -> revision row


def _boom(conn, handle, *, clock, state_dir):
    raise RuntimeError("yahoo wedged")


def test_exception_writes_honesty_letter_before_reraise(tmp_db, fixed_clock, tmp_path):
    import pytest
    from agentcy.jobs import runner
    with pytest.raises(RuntimeError, match="yahoo wedged"):
        runner.sweep_and_run(tmp_db, "daily", _boom, clock=fixed_clock, state_dir=tmp_path)
    # run finished as failed (the key stays honest for the next sweep):
    row = db.fetch_run(tmp_db, "daily", "2026-07-08")
    assert row["status"] == "failed"
    # the honesty letter is IN THE OUTBOX, committed, under the run's primary section key:
    ob = db.fetch_outbox_by_key(tmp_db, "daily:2026-07-08:letter")
    assert ob is not None and ob["status"] == "queued" and ob["kind"] == "daily"
    assert "I just can't see" in ob["payload_html"]


def test_successful_rerun_supersedes_queued_degraded_letter(tmp_db, fixed_clock, tmp_path):
    import pytest
    from agentcy.jobs import runner
    from agentcy.tg import outbox
    with pytest.raises(RuntimeError):
        runner.sweep_and_run(tmp_db, "daily", _boom, clock=fixed_clock, state_dir=tmp_path)
    # simulate the re-run's real letter enqueue for the same key: supersedes in place
    outbox.enqueue(tmp_db, dedupe_key="daily:2026-07-08:letter", kind="daily",
                   payload_html="<b>the real letter</b>", clock=fixed_clock)
    ob = db.fetch_outbox_by_key(tmp_db, "daily:2026-07-08:letter")
    assert ob["payload_html"] == "<b>the real letter</b>"
    assert len(db.fetch_outbox_queued(tmp_db)) == 1


def test_crashed_run_is_reswept_and_real_letter_supersedes_degraded(tmp_db, fixed_clock, tmp_path):
    """FIX.3 (NFR1/§1.3): a crashed 'failed' daily key must be re-claimable by a LATER sweep
    once the flock is released and started_at has aged past the unit timeout. The successful
    re-run supersedes the queued degraded letter IN PLACE under daily:{date}:letter — never a
    duplicate — so the REAL letter is delivered, at worst late, and never silently lost."""
    import pytest
    from datetime import timedelta
    from agentcy.clock import FixedClock
    from agentcy.jobs import runner
    from agentcy.tg import outbox

    # 1) First sweep crashes: ships the degraded honesty letter, finishes 'failed'.
    with pytest.raises(RuntimeError, match="yahoo wedged"):
        runner.sweep_and_run(tmp_db, "daily", _boom, clock=fixed_clock, state_dir=tmp_path)
    row = db.fetch_run(tmp_db, "daily", "2026-07-08")
    assert row["status"] == "failed"
    degraded = db.fetch_outbox_by_key(tmp_db, "daily:2026-07-08:letter")
    assert degraded is not None and degraded["status"] == "queued"
    assert "I just can't see" in degraded["payload_html"]

    # 2) A LATER sweep, past the unit timeout, with a job that succeeds and enqueues the REAL
    #    letter under the same primary key (mirrors the real daily job's supersede-in-place).
    later = FixedClock(fixed_clock.now() + runner.JOB_TIMEOUT + timedelta(minutes=1))

    def _real(conn, handle, *, clock, state_dir):
        key = outbox.scheduled_key(handle.run_type, handle.scheduled_for, "letter")
        outbox.enqueue(conn, dedupe_key=runner.qualified_key(conn, key), kind="daily",
                       payload_html="<b>the real letter</b>", run_id=handle.run_id, clock=clock)
        return "ok", {"ran": True}

    runner.sweep_and_run(tmp_db, "daily", _real, clock=later, state_dir=tmp_path)

    # 3) The failed key was re-claimed and re-run to success.
    row = db.fetch_run(tmp_db, "daily", "2026-07-08")
    assert row["status"] == "ok" and row["finished_at"] is not None
    assert row["attempt"] == 2

    # 4) Exactly ONE outbox row under the crashed key daily:2026-07-08:letter (the degraded
    #    letter was superseded IN PLACE, never a duplicate/revision), carrying the REAL letter.
    ob = db.fetch_outbox_by_key(tmp_db, "daily:2026-07-08:letter")
    assert ob["payload_html"] == "<b>the real letter</b>"
    for_this_key = [r for r in db.fetch_outbox_queued(tmp_db)
                    if r["dedupe_key"].startswith("daily:2026-07-08:letter")]
    assert len(for_this_key) == 1
    assert for_this_key[0]["payload_html"] == "<b>the real letter</b>"


def test_genuinely_successful_key_is_never_reswept(tmp_db, fixed_clock, tmp_path):
    """The re-sweep must NOT re-run a key that genuinely succeeded (status='ok'/'degraded')."""
    from datetime import timedelta
    from agentcy.clock import FixedClock
    from agentcy.jobs import runner
    calls = []
    runner.sweep_and_run(tmp_db, "daily", _recorder(calls, status="ok"), clock=fixed_clock, state_dir=tmp_path)
    assert ("2026-07-08", False) in calls
    later = FixedClock(fixed_clock.now() + runner.JOB_TIMEOUT + timedelta(minutes=1))
    calls.clear()
    runner.sweep_and_run(tmp_db, "daily", _recorder(calls, status="ok"), clock=later, state_dir=tmp_path)
    assert ("2026-07-08", False) not in calls   # ok key not re-swept despite aging


def test_weekly_honesty_letter_lands_under_msg1(tmp_db, tmp_path):
    import pytest
    from datetime import datetime, timezone
    from agentcy.jobs import runner
    sat = FixedClock(datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc))
    with pytest.raises(RuntimeError):
        runner.sweep_and_run(tmp_db, "weekly", _boom, clock=sat, state_dir=tmp_path)
    ob = db.fetch_outbox_by_key(tmp_db, "weekly:2026-07-11:msg1")
    assert ob is not None and ob["kind"] == "weekly_msg"
