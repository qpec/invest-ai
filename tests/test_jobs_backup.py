"""P6.19: backup job — both DBs backed up, retention pruned, integrity checked, rsync + drill."""
from datetime import datetime, timezone
from pathlib import Path

from agentcy import db
from agentcy.clock import FixedClock

NIGHT = FixedClock(datetime(2026, 7, 9, 1, 30, tzinfo=timezone.utc))
SUN = FixedClock(datetime(2026, 7, 12, 1, 30, tzinfo=timezone.utc))   # Sunday -> weekly integrity


def _stub_externals(monkeypatch):
    """No real benchmark.db, no real rsync in the offline suite."""
    from agentcy import benchmark
    from agentcy.jobs import backup
    monkeypatch.setattr(benchmark, "backup_to", lambda dest: Path(dest).write_bytes(b"bm"))
    monkeypatch.setattr(benchmark, "integrity_check", lambda: True)
    monkeypatch.setattr(backup, "rsync_second_disk", lambda src, dest: {"synced": str(src)})


def test_backup_writes_both_dbs_and_records_run(tmp_db, tmp_path, monkeypatch):
    from agentcy.jobs import backup
    _stub_externals(monkeypatch)
    rc = backup.main(clock=NIGHT, state_dir=tmp_path)
    assert rc == 0
    daily_dir = tmp_path / "backups" / "daily"
    names = {p.name for p in daily_dir.iterdir()}
    assert any("agentcy" in n for n in names) and any("benchmark" in n for n in names)
    run = db.fetch_run(db.open_db(tmp_path), "backup", "2026-07-09")
    assert run is not None and run["status"] == "ok"


def test_retention_prunes_beyond_14_daily(tmp_db, tmp_path, monkeypatch):
    from agentcy.jobs import backup
    daily_dir = tmp_path / "backups" / "daily"
    daily_dir.mkdir(parents=True)
    for d in range(20):                                     # 20 stale daily backups
        (daily_dir / f"agentcy-2026-06-{d:02d}.db").write_bytes(b"x")
    backup.prune_retention(daily_dir, keep=14)
    assert len(list(daily_dir.iterdir())) == 14             # oldest pruned, 14 kept


def test_weekly_full_integrity_only_on_sunday(tmp_db, tmp_path, monkeypatch):
    from agentcy.jobs import backup
    _stub_externals(monkeypatch)
    assert backup.integrity_mode(NIGHT.now()) == "quick"    # Thu -> quick_check
    assert backup.integrity_mode(SUN.now()) == "full"       # Sun -> integrity_check


def test_integrity_failure_marks_run_degraded_and_notices(tmp_db, tmp_path, monkeypatch):
    from agentcy.jobs import backup
    _stub_externals(monkeypatch)
    monkeypatch.setattr(backup, "quick_check", lambda conn: False)   # corruption detected
    backup.main(clock=NIGHT, state_dir=tmp_path)
    run = db.fetch_run(db.open_db(tmp_path), "backup", "2026-07-09")
    assert run["status"] == "degraded"
    ob = db.fetch_outbox_by_key(db.open_db(tmp_path), "backup:2026-07-09:notice")
    assert ob is not None and "integrity" in ob["payload_html"].lower()


def test_restore_drill_reports_toolchain_hashes(tmp_db, tmp_path, monkeypatch):
    from agentcy.jobs import backup
    _stub_externals(monkeypatch)
    backup.main(clock=NIGHT, state_dir=tmp_path)
    drill = backup.restore_drill(tmp_path)                  # §12.4 step 1 helper
    assert "agentcy_backup_ok" in drill and "toolchain" in drill
