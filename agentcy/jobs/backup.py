"""Backup job (§11.6). Nightly 03:30. Online Connection.backup() of BOTH DBs, retention
14 daily + 12 monthly, PRAGMA quick_check nightly / integrity_check weekly (Sunday), the
DB backups + recovery toolchain rsync to the second disk /mnt/agentcy-backup, the archive
mirror maintained via gitio.push_backup (R9 — not an rsync of a live .git), plus a
restore-drill helper.

The quarantined benchmark store is touched ONLY through benchmark.py's data-free
maintenance handles (backup_to/integrity_check) — jobs.backup is the second sanctioned
importer, strictly of these no-row handles (§4.6). This module never names that store's
path and NEVER SELECTs benchmark_series (import-graph + source-scan tests, §13).
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from agentcy import benchmark, db, gitio
from agentcy.clock import Clock, SystemClock
from agentcy.jobs import runner
from agentcy.render import contexts
from agentcy.render import daily as render_daily_mod
from agentcy.tg import outbox

RUN_TYPE = "backup"
SECOND_DISK = Path("/mnt/agentcy-backup")                  # S3 confirmed target (§11.6)
TOOLCHAIN_SUBDIR = "toolchain"                             # pinned uv + wheelhouse + interpreter tarball


def integrity_mode(now: datetime) -> str:
    """Full integrity_check on Sunday (weekday()==6), quick_check otherwise (§11.6)."""
    return "full" if now.weekday() == 6 else "quick"


def quick_check(conn) -> bool:
    return conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def full_integrity(conn) -> bool:
    return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def backup_agentcy(conn, dest: Path) -> None:
    """Online, WAL-safe Connection.backup() of agentcy.db to dest (§11.6)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()


def prune_retention(dir_: Path, *, keep: int) -> None:
    """Keep the newest `keep` dated backups per DB family (agentcy-*, benchmark-*); prune older.
    Grouping by prefix means '14 daily' is 14 backup SETS, not 14 files total — otherwise a
    dir holding both families would prune one family's newest to make room for the other's."""
    families: dict[str, list[Path]] = {}
    for p in dir_.iterdir():
        families.setdefault(p.name.rsplit("-", 3)[0], []).append(p)
    for group in families.values():
        group.sort(key=lambda p: p.name)                   # dated filenames sort chronologically
        for old in group[:-keep] if len(group) > keep else []:
            old.unlink()


def rsync_second_disk(src: Path, dest: Path) -> dict:
    """rsync -a the backup tree + toolchain to the second disk (§11.6). Best-effort: a missing
    mount degrades the run, never crashes it (the caller catches and degrades to a notice)."""
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsync", "-a", "--delete", f"{src}/", f"{dest}/"], check=True)
    return {"synced": str(src), "dest": str(dest)}


def restore_drill(state_dir: Path) -> dict:
    """§12.4 step 1: open the newest agentcy backup read-only, integrity-check it, and hash the
    toolchain artifacts on the second disk so the year-8 rebuild is verified, not assumed."""
    daily = state_dir / "backups" / "daily"
    newest = max((p for p in daily.glob("agentcy-*.db")), key=lambda p: p.name, default=None)
    ok = False
    if newest:
        c = sqlite3.connect(f"{newest.as_uri()}?mode=ro", uri=True)
        try:
            ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            c.close()
    toolchain = {}
    tdir = SECOND_DISK / TOOLCHAIN_SUBDIR
    if tdir.exists():
        for artifact in sorted(tdir.iterdir()):
            toolchain[artifact.name] = hashlib.sha256(artifact.read_bytes()).hexdigest()[:16]
    return {"agentcy_backup_ok": ok, "toolchain": toolchain}


def run_one(conn, handle, *, clock: Clock, state_dir: Path) -> tuple[str, dict]:
    """Both-DB backup + retention + integrity + second-disk sync + archive push. Any integrity
    or sync failure -> DEGRADED + an outbox notice (the daemon delivers). A backup failure
    re-raises (OnFailure fires — a box that cannot even write locally is a real failure)."""
    stamp = handle.scheduled_for                           # 'YYYY-MM-DD'
    daily = state_dir / "backups" / "daily"
    backup_agentcy(conn, daily / f"agentcy-{stamp}.db")
    benchmark.backup_to(daily / f"benchmark-{stamp}.db")   # data-free handle (§4.6)
    prune_retention(daily, keep=14)
    monthly = state_dir / "backups" / "monthly"
    monthly.mkdir(parents=True, exist_ok=True)
    if stamp.endswith("-01"):                              # first of month -> monthly copy
        shutil.copy2(daily / f"agentcy-{stamp}.db", monthly / f"agentcy-{stamp}.db")
        prune_retention(monthly, keep=12)
    mode = integrity_mode(clock.now())
    ok_a = (full_integrity(conn) if mode == "full" else quick_check(conn))
    ok_b = benchmark.integrity_check()
    sync = {}
    try:
        sync = rsync_second_disk(state_dir / "backups", SECOND_DISK / "backups")
        # R9/§12.3: the recovery toolchain install.sh staged on-box also mirrors to the second
        # disk here, so restore_drill's year-8 rebuild verification hashes a real artifact.
        sync["toolchain"] = rsync_second_disk(
            state_dir / TOOLCHAIN_SUBDIR, SECOND_DISK / TOOLCHAIN_SUBDIR)
    except Exception as exc:
        sync = {"rsync_error": repr(exc)}
    pushed = gitio.push_backup(state_dir / "archive")      # R9: archive mirror via git push backup
    status = "ok" if (ok_a and ok_b and "rsync_error" not in sync) else "degraded"
    if status == "degraded":
        # Register-safe wording: 'benchmark' is a banned calm-register token outside the
        # quarterly class (render.lint), so the two stores are named advice/index here.
        _notice(conn, handle, clock=clock,
                text=(f"Backup {stamp}: {mode} integrity check advice-store={'ok' if ok_a else 'FAILED'}, "
                      f"index-store={'ok' if ok_b else 'FAILED'}; second-disk sync "
                      f"{'ok' if 'rsync_error' not in sync else 'FAILED'}. "
                      "Nothing is wrong with today's letter; this is the backup channel."))
    conn.commit()
    return status, {"mode": mode, "ok_a": ok_a, "ok_b": ok_b, "sync": sync, "archive_pushed": pushed}


def _notice(conn, handle, *, clock: Clock, text: str) -> None:
    """A calm data-health notice via the daily renderer's total_failure-free 'notice' shape."""
    ctx = contexts.DailyContext(
        kind="total_failure", as_of=clock.now(), header=None, verdict_line=text,
        opportunities=(), more_opportunities=0, events_line=None, data_lines=(text,),
        open_loops=(), open_items_count=0, generated_at=clock.now(), late_banner=None)
    r = render_daily_mod.render_daily(ctx)
    runner.enqueue_rendered(conn, r,
                            base_key=outbox.scheduled_key("backup", handle.scheduled_for, "notice"),
                            kind="notice", run_id=handle.run_id, clock=clock)


def main(*, clock: Clock | None = None, state_dir: Path | None = None) -> int:
    clock = clock or SystemClock()
    state_dir = state_dir or db.state_dir()
    conn = db.open_db(state_dir)
    try:
        return runner.sweep_and_run(conn, RUN_TYPE, run_one, clock=clock, state_dir=state_dir)
    finally:
        conn.close()


if __name__ == "__main__":                                 # R1: systemd ExecStart resolves here
    raise SystemExit(main())
