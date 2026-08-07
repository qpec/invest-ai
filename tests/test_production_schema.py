import sqlite3

import pytest

from agentcy import db


def _seed_run(conn, run_id="run-1", status="VALIDATED"):
    db.append_production_run(conn, {
        "run_id": run_id,
        "mode": "manual",
        "status": status,
        "source_commit": "abc123",
        "started_at": "2026-08-07T12:00:00Z",
    })


def test_production_schema_is_append_only_and_has_one_active_snapshot(tmp_db):
    tables = {row[0] for row in tmp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "production_run",
        "production_top_member",
        "production_thesis_evaluation",
        "production_snapshot",
    } <= tables

    _seed_run(tmp_db)
    db.append_production_top_member(tmp_db, {
        "run_id": "run-1", "security_key": "sec-1", "symbol": "AAA",
        "rank": 1, "score": 91.5,
    })
    db.append_production_thesis_evaluation(tmp_db, {
        "run_id": "run-1", "security_key": "sec-1", "symbol": "AAA",
        "input_fingerprint": "fingerprint", "outcome": "CREATED",
        "evaluated_at": "2026-08-07T12:01:00Z", "reason_code": "NEW_TOP_MEMBER",
        "thesis_version": None,
    })

    for statement in (
        "UPDATE production_top_member SET score=1 WHERE run_id='run-1'",
        "DELETE FROM production_top_member WHERE run_id='run-1'",
        "UPDATE production_thesis_evaluation SET outcome='REUSED' WHERE run_id='run-1'",
        "DELETE FROM production_thesis_evaluation WHERE run_id='run-1'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            tmp_db.execute(statement)


def test_only_one_production_snapshot_can_be_active(tmp_db):
    _seed_run(tmp_db, "run-1")
    _seed_run(tmp_db, "run-2")
    db.append_production_snapshot(tmp_db, {
        "snapshot_id": "snap-1", "run_id": "run-1", "manifest_hash": "hash-1",
        "artifact_path": "/state/staging/snap-1", "created_at": "2026-08-07T12:02:00Z",
        "active": 1, "published_commit": None,
    })
    with pytest.raises(sqlite3.IntegrityError):
        db.append_production_snapshot(tmp_db, {
            "snapshot_id": "snap-2", "run_id": "run-2", "manifest_hash": "hash-2",
            "artifact_path": "/state/staging/snap-2", "created_at": "2026-08-07T12:03:00Z",
            "active": 1, "published_commit": None,
        })


def test_checked_helpers_reject_unknown_production_columns(tmp_db):
    with pytest.raises(ValueError, match="unknown production_run columns"):
        db.append_production_run(tmp_db, {
            "run_id": "run-1", "mode": "manual", "status": "RUNNING",
            "source_commit": "abc123", "started_at": "2026-08-07T12:00:00Z",
            "secret": "must not pass",
        })
