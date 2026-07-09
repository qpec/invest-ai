"""§9 journal-FK, invariant 4 (advice surface), invariant 7 wall 1 (physical absence)."""
from __future__ import annotations

import sqlite3

import pytest

T = "2026-07-08T12:00:00Z"


def test_config_write_without_journal_ref_fails(tmp_db):
    # NOT NULL: an unjournaled config change is impossible, not a code-review finding (§9)
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute(
            "INSERT INTO config (key, value, valid_from) VALUES ('alert_decision_days', '9', ?)",
            (T,))


def test_config_write_with_dangling_journal_ref_fails(tmp_db):
    # FK enforced (open_db sets foreign_keys=ON)
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute(
            "INSERT INTO config (key, value, valid_from, journal_ref)"
            " VALUES ('alert_decision_days', '9', ?, 999999)", (T,))


def test_absence_event_requires_journal_ref(tmp_db):
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute("INSERT INTO absence_event (kind, at) VALUES ('on', ?)", (T,))


def test_thesis_version_requires_journal_ref(tmp_db):
    tmp_db.execute("PRAGMA foreign_keys=OFF")   # isolate the NOT NULL check itself
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute(
            "INSERT INTO thesis_version (thesis_id, version, business_model_2s,"
            " moat_types_json, moat_evidence, owner_earnings_json, owner_earnings_narrative,"
            " fair_band_low, fair_band_high, conviction, mgmt_trust, circle_fit,"
            " time_horizon, ten_year_statement, actor, created_at)"
            " VALUES ('TH-X-001', 1, 'x', '[]', 'x', '{}', 'x', 1, 2,"
            " 'high', 'neutral', 'core', '10y_plus', 'x', 'owner', ?)", (T,))


def test_positions_advice_is_cost_basis_free(tmp_db):
    cols = [d[0] for d in tmp_db.execute("SELECT * FROM positions_advice").description]
    assert "avg_open_price" not in cols


def test_no_benchmark_objects_in_agentcy_db(tmp_db):
    rows = tmp_db.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE '%benchmark%'").fetchall()
    assert rows == []


def test_position_has_no_status_stamp_columns(tmp_db):
    # §4.4 derivations-not-stamps: no framework_status / thesis_id on position
    cols = {r["name"] for r in tmp_db.execute("PRAGMA table_info(position)")}
    assert "framework_status" not in cols and "thesis_id" not in cols


def test_trigger_table_has_no_state_columns(tmp_db):
    cols = {r["name"] for r in tmp_db.execute('PRAGMA table_info("trigger")')}
    assert not {"last_checked", "last_result", "fired_at"} & cols
