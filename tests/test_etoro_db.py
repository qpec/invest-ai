"""Task 2: db helpers for the append-only position_detail table (design 2026-07-10)."""
from __future__ import annotations

from agentcy import db


def test_append_and_fetch_position_details(tmp_db):
    conn = tmp_db
    sid = db.append_snapshot(conn, as_of="2026-07-10", source="api_pull",
                             cash_balance_eur=0.0, created_at="2026-07-10T00:00:00Z")
    db.append_position_details(conn, sid, [{
        "symbol": "AAPL", "opened_at": "2024-01-02", "invested_native": 1000.0,
        "invested_eur": 920.0, "unrealized_pnl_native": 150.0, "unrealized_pnl_pct": 15.0,
        "current_rate": 230.0, "direction": "buy", "lot_count": 2, "raw_json": "[]"}])
    rows = db.fetch_position_details(conn, sid)
    assert rows[0]["symbol"] == "AAPL" and rows[0]["lot_count"] == 2
    assert rows[0]["opened_at"] == "2024-01-02"
