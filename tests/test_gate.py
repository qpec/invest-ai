"""tests/test_gate.py — Gate, watchlist, and gate-session behavior (P4)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agentcy import db


def test_append_gate_session_row(tmp_db):
    sid = db.append_gate_session(tmp_db, ticker="VEEV", mode="gate",
                                 started_at="2026-07-08T05:00:00Z")
    row = db.fetch_active_gate_session(tmp_db, "VEEV")
    assert row is not None
    assert row["session_id"] == sid
    assert row["step"] == "circle"          # DDL default
    assert row["state_json"] == "{}"        # DDL default
    assert row["status"] == "active"        # DDL default
    assert row["mode"] == "gate"


def test_gate_session_identity_guarded(tmp_db):
    db.append_gate_session(tmp_db, ticker="VEEV", mode="gate",
                           started_at="2026-07-08T05:00:00Z")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute("UPDATE gate_session SET ticker='MSFT' WHERE session_id=1")


def test_append_watchlist_item_row(tmp_db):
    item_id = db.append_watchlist_item(tmp_db, ticker="VEEV",
                                       added_at="2026-07-08T05:00:00Z",
                                       idea_source="own_research",
                                       one_line_why="validated GxP record layer")
    rows = db.fetch_watchlist(tmp_db, stage="raw")
    assert [r["item_id"] for r in rows] == [item_id]
    assert rows[0]["one_line_why"] == "validated GxP record layer"
