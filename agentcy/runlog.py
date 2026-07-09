"""Logical run keys, sweep predicates, per-run_type locks (contracts §3.5, tech-arch §1.3)."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from agentcy import config, db
from agentcy.clock import Clock

AMS = ZoneInfo("Europe/Amsterdam")   # job-internal date math via zoneinfo (§1.4)


@dataclass(frozen=True)
class RunHandle:
    run_id: int
    run_type: str
    scheduled_for: str
    late: bool


def start(conn, run_type: str, scheduled_for: str, *, clock: Clock,
          late: bool = False) -> RunHandle:
    """Insert-or-reclaim the UNIQUE(run_type, scheduled_for) row; pins config.effective()."""
    now = db.to_iso(clock.now())
    existing = db.fetch_run(conn, run_type, scheduled_for)
    if existing is not None:
        if existing["finished_at"] is not None:
            raise RuntimeError(
                f"run {run_type}:{scheduled_for} already finished — "
                "callers check is_finished() and exit 0 (§1.3)")
        db.update_run_start(conn, existing["run_id"], started_at=now,
                            attempt=existing["attempt"] + 1, late=late)
        conn.commit()
        return RunHandle(existing["run_id"], run_type, scheduled_for, late)
    inputs = json.dumps({"config": config.effective(conn, as_of=now)}, sort_keys=True)
    cur = conn.execute(
        "INSERT INTO run_log (run_type, scheduled_for, created_at, started_at,"
        " attempt, late, inputs_json) VALUES (?, ?, ?, ?, 1, ?, ?)",
        (run_type, scheduled_for, now, now, int(late), inputs))
    conn.commit()
    return RunHandle(cur.lastrowid, run_type, scheduled_for, late)


def finish(conn, run_id: int, *, status: str, outputs, clock: Clock) -> None:
    """Set finished_at + status + outputs_json; finished keys exit 0 on re-fire."""
    db.update_run_finish(conn, run_id, finished_at=db.to_iso(clock.now()),
                         status=status, outputs_json=json.dumps(outputs, sort_keys=True))
    conn.commit()


def is_finished(conn, run_type: str, scheduled_for: str) -> bool:
    row = db.fetch_run(conn, run_type, scheduled_for)
    return row is not None and row["finished_at"] is not None


# --- per-run_type flock (tech-arch §1.3: 'running' mechanically distinct from 'crashed') ---

try:
    import fcntl

    def _acquire(fd: int, *, blocking: bool) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))

    def _release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)

except ImportError:  # pragma: posix no cover — Windows desk/test fallback ONLY; prod is Ubuntu (§1.1)
    import msvcrt

    def _acquire(fd: int, *, blocking: bool) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)

    def _release(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _lock_path(state_dir: Path, run_type: str) -> Path:
    locks = Path(state_dir) / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    return locks / f"{run_type}.lock"


@contextmanager
def run_lock(state_dir: Path, run_type: str):
    """Per-run_type flock under <state_dir>/locks/, held for the run."""
    fd = os.open(_lock_path(state_dir, run_type), os.O_RDWR | os.O_CREAT)
    try:
        _acquire(fd, blocking=True)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)


def _lock_held(state_dir: Path, run_type: str) -> bool:
    """Non-blocking probe: True when another holder has the lock right now."""
    fd = os.open(_lock_path(state_dir, run_type), os.O_RDWR | os.O_CREAT)
    try:
        try:
            _acquire(fd, blocking=False)
        except OSError:
            return True
        _release(fd)
        return False
    finally:
        os.close(fd)
