import sqlite3

import pytest

from agentcy import db


def test_notes_facts_are_append_only_and_accession_linked(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    conn.execute(
        "INSERT INTO sec_notes_import_run"
        " (archive_name,archive_hash,started_at,finished_at,status,fact_count)"
        " VALUES ('notes.zip','hash','2026-01-01','2026-01-02','SUCCEEDED',1)"
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO sec_notes_fact"
        " (import_run_id,accession,cik,filed_at,form,report_category,report_name,"
        " taxonomy_tag,taxonomy_version,canonical_label,period_end,quarters,unit,"
        " value,source_hash,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, "0001", "0000000001", "2026-01-31", "10-K", "N", "Income Taxes",
         "TaxCustom", "issuer/2025", "Income Tax Expense", "2025-12-31", 4, "USD",
         10.0, "source", "2026-02-01"),
    )
    fact_id = conn.execute("SELECT fact_id FROM sec_notes_fact").fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE sec_notes_fact SET value=11 WHERE fact_id=?", (fact_id,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM sec_notes_fact WHERE fact_id=?", (fact_id,))
