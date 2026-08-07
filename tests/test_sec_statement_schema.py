import sqlite3

import pytest

from agentcy import db


def test_statement_fact_schema_is_append_only_and_indexed(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    conn.execute(
        "INSERT INTO sec_statement_import_run"
        " (archive_name, archive_hash, started_at, finished_at, status, fact_count)"
        " VALUES ('2026q1.zip', 'hash', '2026-04-10T00:00:00Z',"
        " '2026-04-10T00:01:00Z', 'SUCCEEDED', 1)"
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO sec_statement_fact"
        " (import_run_id, accession, cik, filed_at, form, report_period, statement,"
        " taxonomy_tag, taxonomy_version, canonical_label, period_end, quarters, unit,"
        " value, source_hash, imported_at) VALUES"
        " (?, '0001-26-000001', '0000000001', '2026-04-01', '10-K', '2025-12-31',"
        " 'IS', 'RevenueCustom', 'issuer/2025', 'Total Revenue', '2025-12-31', 4,"
        " 'USD', 100, 'fact-hash', '2026-04-10T00:01:00Z')",
        (run_id,),
    )
    fact_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE sec_statement_fact SET value=101 WHERE fact_id=?", (fact_id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM sec_statement_fact WHERE fact_id=?", (fact_id,))
