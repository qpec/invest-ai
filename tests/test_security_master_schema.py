import pytest

from agentcy import db


TABLES = {"security_master_run", "security_observation", "security_alias"}


def test_security_master_migration_creates_contract(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    found = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert TABLES <= found


def _insert_observation(conn):
    conn.execute(
        "INSERT INTO security_master_run"
        " (source_vintage, input_hash, started_at, finished_at, status, input_rows)"
        " VALUES ('2026-08-07', 'input-1', '2026-08-07T08:00:00Z',"
        " '2026-08-07T08:01:00Z', 'SUCCEEDED', 1)"
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO security_observation"
        " (run_id, security_key, cik, symbol, name, country, exchange, instrument_type,"
        "  eligibility, reason_code, source, source_hash, observed_at)"
        " VALUES (?, 'cik:0000000001', '0000000001', 'AAA', 'Acme Inc', 'US',"
        " 'Nasdaq', 'ORDINARY_SHARE', 'ELIGIBLE', 'PRIMARY_ORDINARY_SHARE',"
        " 'sec', 'abc', '2026-08-07T08:00:00Z')",
        (run_id,),
    )
    return run_id


def test_security_observation_is_append_only(tmp_db):
    _insert_observation(tmp_db)
    with pytest.raises(Exception):
        tmp_db.execute("UPDATE security_observation SET symbol='BBB'")
    with pytest.raises(Exception):
        tmp_db.execute("DELETE FROM security_observation")


def test_current_view_reads_latest_successful_run_only(tmp_db):
    first_run = _insert_observation(tmp_db)
    tmp_db.execute(
        "INSERT INTO security_master_run"
        " (source_vintage, input_hash, started_at, status, input_rows)"
        " VALUES ('2026-08-08', 'input-2', '2026-08-08T08:00:00Z', 'RUNNING', 1)"
    )
    running_id = tmp_db.execute("SELECT last_insert_rowid()").fetchone()[0]
    tmp_db.execute(
        "INSERT INTO security_observation"
        " (run_id, security_key, cik, symbol, name, country, exchange, instrument_type,"
        "  eligibility, reason_code, source, source_hash, observed_at)"
        " VALUES (?, 'cik:0000000001', '0000000001', 'NEW', 'Acme Inc', 'US',"
        " 'Nasdaq', 'ORDINARY_SHARE', 'ELIGIBLE', 'PRIMARY_ORDINARY_SHARE',"
        " 'sec', 'def', '2026-08-08T08:00:00Z')",
        (running_id,),
    )
    current = tmp_db.execute("SELECT * FROM v_current_security").fetchall()
    assert len(current) == 1
    assert current[0]["run_id"] == first_run
    assert current[0]["symbol"] == "AAA"


def test_security_enums_reject_unknown_values(tmp_db):
    run_id = _insert_observation(tmp_db)
    with pytest.raises(Exception):
        tmp_db.execute(
            "INSERT INTO security_observation"
            " (run_id, security_key, symbol, name, instrument_type, eligibility,"
            "  reason_code, source, source_hash, observed_at)"
            " VALUES (?, 'symbol:BAD', 'BAD', 'Bad', 'ALIEN', 'ELIGIBLE',"
            " 'PRIMARY_ORDINARY_SHARE', 'test', 'bad', '2026-08-07T08:00:00Z')",
            (run_id,),
        )
