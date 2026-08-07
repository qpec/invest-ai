import pytest

from agentcy import db


TABLES = {
    "market_price_refresh_run",
    "market_price_attempt",
    "market_price_observation",
}


def _run(conn, *, scheduled_for="2026-08-07", status="RUNNING", promoted=0):
    conn.execute(
        "INSERT INTO market_price_refresh_run"
        " (scheduled_for, attempt, started_at, status, selected_count, promoted)"
        " VALUES (?, 1, '2026-08-07T10:00:00Z', ?, 1, ?)",
        (scheduled_for, status, promoted),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _observation(conn, run_id, *, symbol="ACME", payload_hash="hash-1"):
    conn.execute(
        "INSERT INTO market_price_observation"
        " (refresh_run_id, security_key, provider, provider_symbol, bar_date,"
        " raw_close, adjusted_close, dividend, split_ratio, currency, fetched_at,"
        " payload_hash) VALUES (?, 'cik:0000000001', 'yahoo', ?, '2026-08-06',"
        " 25.0, 24.5, 0.0, NULL, 'USD', '2026-08-07T10:01:00Z', ?)",
        (run_id, symbol, payload_hash),
    )


def test_market_price_migration_creates_contract(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    found = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert TABLES <= found


def test_price_evidence_is_append_only(tmp_db):
    run_id = _run(tmp_db)
    _observation(tmp_db, run_id)
    tmp_db.execute(
        "INSERT INTO market_price_attempt"
        " (refresh_run_id, security_key, provider_symbol, attempt_no, attempted_at,"
        " outcome) VALUES (?, 'cik:0000000001', 'ACME', 1,"
        " '2026-08-07T10:01:00Z', 'OK')",
        (run_id,),
    )
    for table in ("market_price_observation", "market_price_attempt"):
        with pytest.raises(Exception):
            tmp_db.execute(f"UPDATE {table} SET rowid=rowid")
        with pytest.raises(Exception):
            tmp_db.execute(f"DELETE FROM {table}")


def test_price_replay_is_idempotent(tmp_db):
    run_id = _run(tmp_db)
    _observation(tmp_db, run_id)
    with pytest.raises(Exception):
        _observation(tmp_db, run_id)


def test_current_prices_only_read_latest_promoted_success(tmp_db):
    first = _run(tmp_db, scheduled_for="2026-08-06", status="SUCCEEDED", promoted=1)
    _observation(tmp_db, first, payload_hash="old")
    running = _run(tmp_db, scheduled_for="2026-08-07")
    _observation(tmp_db, running, payload_hash="new")
    current = tmp_db.execute("SELECT * FROM v_current_market_price").fetchall()
    assert len(current) == 1
    assert current[0]["payload_hash"] == "old"


def test_price_constraints_reject_invalid_values(tmp_db):
    run_id = _run(tmp_db)
    with pytest.raises(Exception):
        tmp_db.execute(
            "INSERT INTO market_price_observation"
            " (refresh_run_id, security_key, provider, provider_symbol, bar_date,"
            " raw_close, adjusted_close, dividend, currency, fetched_at, payload_hash)"
            " VALUES (?, 'cik:1', 'yahoo', 'BAD', '2026-08-06', 0, 1, 0, 'USD',"
            " '2026-08-07T10:00:00Z', 'bad')",
            (run_id,),
        )
