"""Migration 001 adds the append-only position_detail companion table (design 2026-07-10).

Never read by positions_advice / the balance path (invariant 4 stays clean);
thesis/journal/reporting only. UPDATE and DELETE must abort (invariant 1)."""
from __future__ import annotations

import sqlite3


def test_position_detail_table_exists_and_is_append_only(tmp_db):
    conn = tmp_db  # fresh, fully-migrated agentcy.db (conftest applies schema/NNN_*.sql)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(position_detail)")}
    assert {"snapshot_id", "symbol", "opened_at", "invested_native", "invested_eur",
            "unrealized_pnl_native", "unrealized_pnl_pct", "current_rate", "direction",
            "lot_count", "raw_json"} <= cols

    conn.execute(
        "INSERT INTO snapshot (as_of, source, cash_balance_eur, created_at) "
        "VALUES ('2026-07-10','api_pull',0,'2026-07-10T00:00:00Z')")
    sid = conn.execute("SELECT snapshot_id FROM snapshot").fetchone()[0]
    conn.execute("INSERT INTO position_detail (snapshot_id, symbol) VALUES (?, 'AAPL')", (sid,))

    for stmt in ("UPDATE position_detail SET direction='buy'",
                 "DELETE FROM position_detail"):
        try:
            conn.execute(stmt)
            assert False, f"{stmt} should abort (append-only, invariant 1)"
        except sqlite3.IntegrityError:
            pass
