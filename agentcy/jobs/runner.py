"""Job runner — the run_type-scoped due-run sweep (tech-arch §1.3, review-fixed).

Each job's sweep re-runs ONLY its own run_type's due keys (the quarterly job, and
therefore the benchmark, can never be pulled into another process). A per-run_type
flock held for the run makes 'currently running' mechanically distinct from
'crashed'; started-but-unfinished keys are re-runnable only when unlocked AND
started_at is older than the unit's TimeoutStartSec (JOB_TIMEOUT mirrors 30min).
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from agentcy import db, runlog
from agentcy.clock import Clock

JOB_TIMEOUT = timedelta(minutes=30)  # mirrors TimeoutStartSec=30min (tech-arch §1.2)

# Where each run_type's degraded honesty letter lands: (section, outbox kind).
PRIMARY_SECTION = {
    "daily": ("letter", "daily"),
    "weekly": ("msg1", "weekly_msg"),
    "quarterly": ("summary", "quarterly_msg"),
    "event": ("report", "event"),
    "backup": ("notice", "notice"),
}


def qualified_key(conn, base: str) -> str:
    """base while free/queued (supersession applies); '#a{n}' revision key once sent (§5.4)."""
    row = db.fetch_outbox_by_key(conn, base)
    if row is None or row["status"] == "queued":
        return base
    n = 2
    while True:
        k = f"{base}#a{n}"
        row = db.fetch_outbox_by_key(conn, k)
        if row is None or row["status"] == "queued":
            return k
        n += 1


def sweep_and_run(conn, run_type: str, job_fn, *, clock: Clock, state_dir: Path,
                  timeout: timedelta = JOB_TIMEOUT) -> int:
    """For every due key of run_type absent or crashed (per runlog.sweepable), run job_fn
    under the per-type lock. Finished keys exit 0. The newest due key is on-time; every
    other swept key is marked late. Plan note: sweepable is computed BEFORE taking our
    own lock (flock is per-open-file-description — probing a lock we hold would misread),
    then each key is re-checked with is_finished inside the lock."""
    keys = runlog.sweepable(conn, run_type, as_of=clock.now(), timeout=timeout, state_dir=state_dir)
    if not keys:
        return 0
    newest = max(keys)
    with runlog.run_lock(state_dir, run_type):
        for key in sorted(keys):
            if runlog.is_finished(conn, run_type, key):
                continue
            handle = runlog.start(conn, run_type, key, clock=clock, late=(key != newest))
            conn.commit()
            try:
                status, outputs = job_fn(conn, handle, clock=clock, state_dir=state_dir)
            except Exception as exc:                      # degraded-letter guard: P6.3
                _on_job_exception(conn, handle, clock=clock, exc=exc)
                raise                                     # OnFailure= fires AND the letter shipped
            runlog.finish(conn, handle.run_id, status=status, outputs=outputs, clock=clock)
            conn.commit()
    return 0


def _on_job_exception(conn, handle, *, clock, exc) -> None:
    """Placeholder until P6.3: finish the run as failed so the key stays sweepable-honest."""
    runlog.finish(conn, handle.run_id, status="failed", outputs={"error": repr(exc)}, clock=clock)
    conn.commit()
