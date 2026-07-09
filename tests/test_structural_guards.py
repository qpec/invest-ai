"""Operational tables: identity columns immutable, state columns updatable, no deletes (tech-arch §4.1/§4.2).
Plus the two special guards: "trigger".retired_at write-once and the outbox queued-only payload guard."""
from __future__ import annotations

import sqlite3

import pytest

T = "2026-07-08T00:00:00Z"

# (table, seed_sql or None, identity_update_sql, allowed_update_sql)
GUARD_CASES = [
    ("run_log",
     f"INSERT INTO run_log (run_type, scheduled_for, created_at, started_at)"
     f" VALUES ('daily', '2026-07-08', '{T}', '{T}')",
     "UPDATE run_log SET run_type = 'weekly'",
     f"UPDATE run_log SET finished_at = '{T}', status = 'ok'"),
    ("ask",
     f"INSERT INTO ask (ask_id, kind, seq, created_at, prompt, options_json)"
     f" VALUES ('A1', 'A', 1, '{T}', 'Confirm broken?', '[]')",
     "UPDATE ask SET prompt = 'rewritten'",
     f"UPDATE ask SET status = 'answered', answered_at = '{T}'"),
    ("alert",
     f"INSERT INTO alert (thesis_id, trigger_id, run_id, created_at, deadline)"
     f" VALUES ('TH-MSFT-001', 1, 1, '{T}', '2026-07-15T00:00:00Z')",
     "UPDATE alert SET deadline = '2027-01-01T00:00:00Z'",
     f"UPDATE alert SET status = 'refuted', resolved_at = '{T}'"),
    ("outbox",
     f"INSERT INTO outbox (dedupe_key, kind, created_at, payload_html)"
     f" VALUES ('daily:2026-07-08:letter', 'daily', '{T}', '<b>x</b>')",
     "UPDATE outbox SET dedupe_key = 'other'",
     "UPDATE outbox SET attempts = 1, next_attempt_at = '2026-07-08T00:01:00Z'"),
    ("watchlist_item",
     f"INSERT INTO watchlist_item (ticker, added_at, idea_source, one_line_why)"
     f" VALUES ('ASML', '{T}', 'own_research', 'EUV monopoly')",
     "UPDATE watchlist_item SET ticker = 'X'",
     f"UPDATE watchlist_item SET stage = 'expired', stage_changed_at = '{T}'"),
    ("bot_state", None,
     "UPDATE bot_state SET id = 2",
     "UPDATE bot_state SET last_update_id = 7"),
    ("gate_session",
     f"INSERT INTO gate_session (ticker, mode, started_at) VALUES ('ASML', 'gate', '{T}')",
     "UPDATE gate_session SET ticker = 'X'",
     f"UPDATE gate_session SET step = 'dossier', updated_at = '{T}'"),
    ("study_state", None,
     "UPDATE study_state SET id = 2",
     f"UPDATE study_state SET mental_model_index = 3, updated_at = '{T}'"),
]


@pytest.mark.parametrize("table,seed,identity_sql,allowed_sql",
                         GUARD_CASES, ids=[c[0] for c in GUARD_CASES])
def test_column_guard(tmp_db, table, seed, identity_sql, allowed_sql):
    tmp_db.execute("PRAGMA foreign_keys=OFF")
    if seed is not None:
        tmp_db.execute(seed)
    with pytest.raises(sqlite3.IntegrityError, match="column guard|immutable"):
        tmp_db.execute(identity_sql)
    assert tmp_db.execute(allowed_sql).rowcount >= 1        # state columns stay writable
    with pytest.raises(sqlite3.IntegrityError, match="no delete"):
        tmp_db.execute(f'DELETE FROM "{table}"')


def _seed_trigger(conn):
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO \"trigger\" (thesis_id, introduced_version, type, statement,"
        " persistence, check_method, data_source, cadence)"
        " VALUES ('TH-MSFT-001', 1, 'growth_floor', 'Revenue growth stays above 10%',"
        " 'ttm', 'automated', 'yf_quarterly_statements', 'weekly')")


def test_trigger_retired_at_is_write_once(tmp_db):
    _seed_trigger(tmp_db)
    tmp_db.execute(f"UPDATE \"trigger\" SET retired_at = '{T}'")   # the sole allowed UPDATE
    with pytest.raises(sqlite3.IntegrityError, match="write-once"):
        tmp_db.execute("UPDATE \"trigger\" SET retired_at = '2026-08-01T00:00:00Z'")
    with pytest.raises(sqlite3.IntegrityError, match="write-once"):
        tmp_db.execute("UPDATE \"trigger\" SET retired_at = NULL")  # un-retiring is mutation too


def test_trigger_definition_columns_immutable(tmp_db):
    _seed_trigger(tmp_db)
    for sql in ("UPDATE \"trigger\" SET threshold = 5.0",
                "UPDATE \"trigger\" SET comparator = '>'",
                "UPDATE \"trigger\" SET cadence = 'event'"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            tmp_db.execute(sql)


def test_outbox_payload_supersedable_only_while_queued(tmp_db):
    tmp_db.execute("PRAGMA foreign_keys=OFF")
    tmp_db.execute(
        f"INSERT INTO outbox (dedupe_key, kind, created_at, payload_html)"
        f" VALUES ('daily:2026-07-08:letter', 'daily', '{T}', '<b>v1</b>')")
    tmp_db.execute("UPDATE outbox SET payload_html = '<b>v2</b>'")          # queued: OK (§5.4)
    tmp_db.execute("UPDATE outbox SET status = 'sent', tg_message_id = 42")
    with pytest.raises(sqlite3.IntegrityError, match="supersedable only while queued"):
        tmp_db.execute("UPDATE outbox SET payload_html = '<b>v3</b>'")
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute("UPDATE outbox SET document_path = '/tmp/x.md'")
