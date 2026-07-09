"""Update helpers touch exactly the guarded state columns (contracts §3.1)."""
from __future__ import annotations

import sqlite3

import pytest

from agentcy import db

T = "2026-07-08T05:00:00Z"
T2 = "2026-07-08T06:00:00Z"


def _seed_ask(conn):
    conn.execute(
        "INSERT INTO ask (ask_id, kind, seq, created_at, prompt, options_json)"
        " VALUES ('A1', 'A', 1, ?, 'Confirm?', '[]')", (T,))


def test_update_ask_state(tmp_db):
    _seed_ask(tmp_db)
    db.update_ask_state(tmp_db, "A1", status="answered",
                        answer_json='{"choice":"confirm"}', answered_at=T2,
                        tg_message_id=99)
    row = db.fetch_ask(tmp_db, "A1")
    assert row["status"] == "answered" and row["tg_message_id"] == 99


def test_update_missing_row_raises(tmp_db):
    with pytest.raises(LookupError):
        db.update_ask_state(tmp_db, "A9", status="answered")


def test_supersede_outbox_payload_only_while_queued(tmp_db):
    tmp_db.execute(
        "INSERT INTO outbox (dedupe_key, kind, created_at, payload_html)"
        " VALUES ('daily:2026-07-08:letter', 'daily', ?, '<b>v1</b>')", (T,))
    oid = tmp_db.execute("SELECT outbox_id FROM outbox").fetchone()[0]
    db.supersede_outbox_payload(tmp_db, oid, payload_html="<b>v2</b>")
    assert db.fetch_outbox_by_key(
        tmp_db, "daily:2026-07-08:letter")["payload_html"] == "<b>v2</b>"
    db.update_outbox_state(tmp_db, oid, status="sent", tg_message_id=5)
    with pytest.raises(sqlite3.IntegrityError):        # DB guard, not Python logic (§5.4)
        db.supersede_outbox_payload(tmp_db, oid, payload_html="<b>v3</b>")


def test_retire_trigger_write_once(tmp_db):
    db.append_thesis(tmp_db, thesis_id="TH-MSFT-001", ticker="MSFT",
                     origin="gate", created_at=T)
    tid = db.append_trigger(tmp_db, {
        "thesis_id": "TH-MSFT-001", "introduced_version": 1, "type": "growth_floor",
        "statement": "s", "persistence": "ttm", "check_method": "automated",
        "data_source": "yf_quarterly_statements", "cadence": "weekly"})
    db.retire_trigger(tmp_db, tid, retired_at=T)
    with pytest.raises(sqlite3.IntegrityError):
        db.retire_trigger(tmp_db, tid, retired_at=T2)


def test_run_alert_watchlist_gate_study_bot_updates(tmp_db):
    rid = tmp_db.execute(
        "INSERT INTO run_log (run_type, scheduled_for, created_at, started_at)"
        " VALUES ('daily', '2026-07-08', ?, ?)", (T, T)).lastrowid
    db.update_run_start(tmp_db, rid, started_at=T2, attempt=2, late=True)
    db.update_run_finish(tmp_db, rid, finished_at=T2, status="ok",
                         outputs_json='{"letters":1}')
    row = db.fetch_run(tmp_db, "daily", "2026-07-08")
    assert row["attempt"] == 2 and row["late"] == 1 and row["status"] == "ok"

    tmp_db.commit()  # PRAGMA foreign_keys is a no-op inside an open transaction
    tmp_db.execute("PRAGMA foreign_keys=OFF")
    tmp_db.execute(
        "INSERT INTO alert (thesis_id, trigger_id, run_id, created_at, deadline)"
        " VALUES ('TH-X-001', 1, 1, ?, ?)", (T, T2))
    aid = tmp_db.execute("SELECT alert_id FROM alert").fetchone()[0]
    db.update_alert_resolution(tmp_db, aid, status="refuted", resolved_at=T2,
                               resolution_journal_ref=1)
    assert db.fetch_alert(tmp_db, aid)["status"] == "refuted"

    tmp_db.execute(
        "INSERT INTO watchlist_item (ticker, added_at, idea_source, one_line_why)"
        " VALUES ('ASML', ?, 'reading', 'x')", (T,))
    iid = tmp_db.execute("SELECT item_id FROM watchlist_item").fetchone()[0]
    db.update_watchlist_stage(tmp_db, iid, stage="gate_approved_waiting",
                              stage_changed_at=T2, thesis_ref=None)
    assert db.fetch_watchlist(tmp_db, stage="gate_approved_waiting")[0]["item_id"] == iid

    tmp_db.execute(
        "INSERT INTO gate_session (ticker, mode, started_at) VALUES ('ASML', 'gate', ?)",
        (T,))
    sid = tmp_db.execute("SELECT session_id FROM gate_session").fetchone()[0]
    db.update_gate_session(tmp_db, sid, step="dossier", state_json='{"a":1}',
                           status="active", updated_at=T2)
    assert db.fetch_active_gate_session(tmp_db, "ASML")["step"] == "dossier"

    db.update_bot_state(tmp_db, last_update_id=123)
    assert db.fetch_bot_state(tmp_db)["last_update_id"] == 123
    db.update_study_state(tmp_db, last_restudied_thesis_id="TH-X-001",
                          mental_model_index=4, updated_at=T2)
    assert db.fetch_study_state(tmp_db)["mental_model_index"] == 4
