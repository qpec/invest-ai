"""db.py basics: state_dir resolution, ISO-8601 round-trip."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from agentcy import db


def test_state_dir_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    assert db.state_dir() == tmp_path


def test_state_dir_default(monkeypatch):
    monkeypatch.delenv("AGENTCY_STATE_DIR", raising=False)
    assert db.state_dir() == Path("/var/lib/stock-agentcy")


def test_to_iso_normalizes_to_utc_z():
    cet = timezone(timedelta(hours=2))
    assert db.to_iso(datetime(2026, 7, 8, 7, 0, tzinfo=cet)) == "2026-07-08T05:00:00Z"


def test_to_iso_rejects_naive():
    with pytest.raises(ValueError):
        db.to_iso(datetime(2026, 7, 8, 7, 0))


def test_from_iso_round_trip():
    dt = db.from_iso("2026-07-08T05:00:00Z")
    assert dt == datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)
    assert db.to_iso(dt) == "2026-07-08T05:00:00Z"


import hashlib
import sqlite3

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "agentcy" / "schema"


def test_open_db_pragmas_and_row_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    conn = db.open_db(tmp_path)
    assert conn.row_factory is sqlite3.Row
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    assert (tmp_path / "agentcy.db").exists()
    assert not (tmp_path / "benchmark.db").exists()   # invariant 7: never opened here
    conn.close()


def test_migrate_applies_000_once_and_records(tmp_path):
    # isolate to only 000 so this test proves "000 applies once + records" independent of
    # how many later migrations exist (001+ are exercised by their own suites).
    import shutil
    sd = tmp_path / "schema"
    sd.mkdir()
    shutil.copy(SCHEMA_DIR / "000_init.sql", sd / "000_init.sql")
    conn = db.open_db(tmp_path)
    assert db.migrate(conn, schema_dir=sd) == [0]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    row = conn.execute("SELECT * FROM schema_migration WHERE version=0").fetchone()
    sql = (SCHEMA_DIR / "000_init.sql").read_text(encoding="utf-8")
    assert row["sha256"] == hashlib.sha256(sql.encode("utf-8")).hexdigest()
    db.from_iso(row["applied_at"])                     # parses as contract ISO format
    assert db.migrate(conn, schema_dir=sd) == []       # idempotent re-run
    conn.close()


def test_migrate_never_picks_up_benchmark_file(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE '%benchmark%'")}
    assert names == set()
    conn.close()


def test_migrate_raises_on_gap(tmp_path):
    import shutil
    sd = tmp_path / "schema"
    sd.mkdir()
    shutil.copy(SCHEMA_DIR / "000_init.sql", sd / "000_init.sql")
    (sd / "002_orphan.sql").write_text("CREATE TABLE oops (x);", encoding="utf-8")
    conn = db.open_db(tmp_path)
    with pytest.raises(RuntimeError, match="gap"):
        db.migrate(conn, schema_dir=sd)
    conn.close()
