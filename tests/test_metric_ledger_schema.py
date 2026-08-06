"""Schema contracts for the append-only Metric Evidence Ledger."""
from __future__ import annotations

import sqlite3

import pytest

from agentcy import db


LEDGER_TABLES = {
    "metric_definition",
    "source_observation",
    "metric_observation",
    "metric_input",
    "source_policy",
    "ledger_refresh_run",
    "parity_result",
}

LEDGER_VIEWS = {
    "v_current_metric",
    "v_stock_data_health",
    "v_metric_coverage",
}


def _migrated(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    return conn


def test_ledger_migration_creates_tables_and_views(tmp_path):
    conn = _migrated(tmp_path)
    objects = {(row["type"], row["name"]) for row in conn.execute(
        "SELECT type, name FROM sqlite_master")}
    assert {("table", name) for name in LEDGER_TABLES} <= objects
    assert {("view", name) for name in LEDGER_VIEWS} <= objects


def test_source_observation_rejects_update_and_delete(tmp_path):
    conn = _migrated(tmp_path)
    run_id = conn.execute(
        "INSERT INTO ledger_refresh_run"
        " (run_type, scheduled_for, attempt, started_at, status, catch_up)"
        " VALUES ('sec_delta', '2026-08-06', 1, '2026-08-06T06:00:00Z',"
        " 'RUNNING', 0)"
    ).lastrowid
    observation_id = conn.execute(
        "INSERT INTO source_observation"
        " (ticker, source, source_key, value, unit, period_end, filed_at,"
        " fetched_at, payload_hash, refresh_run_id)"
        " VALUES ('ACME', 'sec', 'Revenue', 100.0, 'USD', '2026-06-30',"
        " '2026-08-01T10:00:00Z', '2026-08-01T11:00:00Z', 'hash-1', ?)",
        (run_id,),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE source_observation SET value=101 WHERE observation_id=?",
                     (observation_id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM source_observation WHERE observation_id=?",
                     (observation_id,))


def test_metric_status_constraint_rejects_unknown_state(tmp_path):
    conn = _migrated(tmp_path)
    definition_id = conn.execute(
        "INSERT INTO metric_definition"
        " (metric_key, formula_version, unit, requirement, freshness_policy,"
        " active_from, created_at)"
        " VALUES ('owner_fcf_margin_pct', 'v1', '%', 'REQUIRED',"
        " 'filing_aware', '2026-08-06', '2026-08-06T06:00:00Z')"
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
        conn.execute(
            "INSERT INTO metric_observation"
            " (metric_definition_id, ticker, value, status, confidence, as_of,"
            " calculated_at) VALUES (?, 'ACME', 18.2, 'MAYBE', 1.0,"
            " '2026-06-30', '2026-08-06T06:05:00Z')",
            (definition_id,),
        )
