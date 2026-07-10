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
        if existing["finished_at"] is not None and existing["status"] != "failed":
            raise RuntimeError(
                f"run {run_type}:{scheduled_for} already finished — "
                "callers check is_finished() and exit 0 (§1.3)")
        # A FAILED key kept finished_at (so /status stays honest) but never produced its real
        # letter; a later sweep re-claims it to re-run (FIX.3). update_run_start clears the
        # stale finish so the re-run's runlog.finish stamps the successful outcome.
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


def is_done(conn, run_type: str, scheduled_for: str) -> bool:
    """Genuinely complete — finished AND not a re-claimable 'failed' key. The sweep loop uses
    this (not is_finished) so a crashed key that another process finished ON TIME between the
    sweepable() scan and the lock is skipped, while a 'failed' key is still re-run (FIX.3)."""
    row = db.fetch_run(conn, run_type, scheduled_for)
    return row is not None and row["finished_at"] is not None and row["status"] != "failed"


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


# --- due keys & sweep predicates (§1.3: each job sweeps only its OWN run_type) ---

_FIRE = {"daily": time(7, 0), "weekly": time(8, 0),
         "quarterly": time(8, 30), "backup": time(3, 30)}   # §1.1 timer table, Europe/Amsterdam
_LOOKBACK = {"daily": 14, "backup": 14, "weekly": 6, "quarterly": 2}


def due_keys(run_type: str, *, as_of: datetime) -> list[str]:
    """Logical keys due by as_of (daily: every calendar day incl. weekend pulse;
    weekly: Saturdays; quarterly: 1 Jan/Apr/Jul/Oct). Keys are Amsterdam dates."""
    if run_type not in _FIRE:
        return []          # event/gate/scout/snapshot/desk keys are object identities
    fire, lookback = _FIRE[run_type], _LOOKBACK[run_type]
    local_today = as_of.astimezone(AMS).date()
    keys: list[str] = []
    if run_type in ("daily", "backup"):
        day = local_today
        while len(keys) < lookback:
            if datetime.combine(day, fire, tzinfo=AMS) <= as_of:
                keys.append(day.isoformat())
            day -= timedelta(days=1)
    elif run_type == "weekly":
        day = local_today
        while len(keys) < lookback:
            if day.weekday() == 5 and datetime.combine(day, fire, tzinfo=AMS) <= as_of:
                keys.append(day.isoformat())
            day -= timedelta(days=1)
    else:  # quarterly: 1 Jan/Apr/Jul/Oct
        y, m = local_today.year, ((local_today.month - 1) // 3) * 3 + 1
        while len(keys) < lookback:
            day = date(y, m, 1)
            if datetime.combine(day, fire, tzinfo=AMS) <= as_of:
                keys.append(day.isoformat())
            m -= 3
            if m < 1:
                m, y = m + 12, y - 1
    return sorted(keys)


def sweepable(conn, run_type: str, *, as_of: datetime, timeout: timedelta,
              state_dir: Path) -> list[str]:
    """Own-run_type due keys absent OR re-claimable AND unlocked AND started_at older than
    timeout (§1.3). A key is re-claimable when it is started-but-unfinished OR it FAILED —
    a crashed run stamps finished_at (so /status stays honest) but its real letter was never
    produced, so a later sweep must re-run it (FIX.3, NFR1/§1.3). A key that genuinely
    succeeded (status 'ok'/'degraded' with finished_at) is never re-swept."""
    out: list[str] = []
    for key in due_keys(run_type, as_of=as_of):
        row = db.fetch_run(conn, run_type, key)
        if row is None:
            out.append(key)
            continue
        if row["finished_at"] is not None and row["status"] != "failed":
            continue                                  # genuinely done — never re-run
        if as_of - db.from_iso(row["started_at"]) <= timeout:
            continue                                  # possibly still running
        if _lock_held(state_dir, run_type):
            continue                                  # mechanically running right now
        out.append(key)
    return out


def report_missing(conn, *, as_of: datetime) -> list[str]:
    """Daemon startup sweep: DETECT AND REPORT only — never executes jobs (§1.3)."""
    missing: list[str] = []
    for run_type in ("daily", "weekly", "quarterly", "backup"):
        for key in due_keys(run_type, as_of=as_of):
            if not is_finished(conn, run_type, key):
                missing.append(f"{run_type}:{key}")
    return missing
