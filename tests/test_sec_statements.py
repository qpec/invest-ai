import zipfile

from agentcy import db


def _archive(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "sub.txt",
            "adsh\tcik\tname\tform\tperiod\tfiled\n"
            "0001-26-000001\t1\tAcme\t10-K\t20251231\t20260301\n",
        )
        archive.writestr(
            "pre.txt",
            "adsh\treport\tline\tstmt\tinpth\trfile\ttag\tversion\tplabel\tnegating\n"
            "0001-26-000001\t1\t1\tIS\t0\tH\tRevenueCustom\tacme/2025\tTotal revenues\t0\n"
            "0001-26-000001\t1\t2\tIS\t0\tH\tMystery\tacme/2025\tMystery subtotal\t0\n",
        )
        archive.writestr(
            "num.txt",
            "adsh\ttag\tversion\tddate\tqtrs\tuom\tsegments\tcoreg\tvalue\tfootnote\n"
            "0001-26-000001\tRevenueCustom\tacme/2025\t20251231\t4\tUSD\t\t\t100\t\n"
            "0001-26-000001\tRevenueCustom\tacme/2025\t20251231\t4\tUSD\tsegment\t\t90\t\n"
            "0001-26-000001\tMystery\tacme/2025\t20251231\t4\tUSD\t\t\t50\t\n",
        )


def test_import_archive_accepts_allowlisted_custom_label_only(tmp_path):
    from agentcy.sec_statements import import_archive

    archive = tmp_path / "2026q1.zip"
    _archive(archive)
    conn = db.open_db(tmp_path / "state")
    db.migrate(conn)

    result = import_archive(
        conn, archive, eligible_ciks={"0000000001"},
        imported_at="2026-04-10T00:00:00Z",
    )

    assert result == {"facts": 1, "status": "SUCCEEDED"}
    row = conn.execute("SELECT * FROM sec_statement_fact").fetchone()
    assert row["canonical_label"] == "Total Revenue"
    assert row["quarters"] == 4
    assert row["value"] == 100.0


def test_long_term_debt_alone_is_not_total_debt():
    from agentcy.sec_statements import canonical_labels

    assert canonical_labels("LongTermDebt", "") == ()
    assert canonical_labels("DebtLongtermAndShorttermCombinedAmount", "") == ("Total Debt",)


def test_supplement_bundle_fills_only_absent_rows_and_refuses_conflicts(tmp_path):
    from agentcy.sec_statements import supplement_bundle

    conn = db.open_db(tmp_path)
    db.migrate(conn)
    conn.execute(
        "INSERT INTO sec_statement_import_run"
        " (archive_name,archive_hash,started_at,finished_at,status,fact_count)"
        " VALUES ('q.zip','hash','2026-01-01T00:00:00Z','2026-01-01T00:01:00Z',"
        " 'SUCCEEDED',3)"
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    base = (run_id, "0001", "0000000001", "2026-03-01", "10-K", "2025-12-31",
            "IS", "Custom", "issuer/2025", "2025-12-31", 4, "USD",
            "2026-03-02T00:00:00Z")
    for label, value, source_hash in (
        ("Total Revenue", 100.0, "a"),
        ("Operating Income", 25.0, "b"),
        ("Operating Income", 30.0, "c"),
    ):
        conn.execute(
            "INSERT INTO sec_statement_fact"
            " (import_run_id,accession,cik,filed_at,form,report_period,statement,"
            " taxonomy_tag,taxonomy_version,canonical_label,period_end,quarters,unit,"
            " value,source_hash,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*base[:9], label, *base[9:12], value, source_hash, base[12]),
        )
    conn.execute(
        "INSERT INTO sec_statement_fact"
        " (import_run_id,accession,cik,filed_at,form,report_period,statement,"
        " taxonomy_tag,taxonomy_version,canonical_label,period_end,quarters,unit,"
        " value,source_hash,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (*base[:9], "Total Revenue", "2024-12-31", 4, "USD", 80.0, "older", base[12]),
    )
    bundle = {
        "annual": {"income": {"2025-12-31": {"Total Revenue": 90.0}},
                   "balance": {}, "cashflow": {}},
        "quarterly": {"income": {}, "balance": {}, "cashflow": {}},
        "supplements": {"flows": {}, "points": {}},
    }

    result = supplement_bundle(conn, cik="0000000001", as_of="2026-08-07", bundle=bundle)

    assert result["annual"]["income"]["2025-12-31"]["Total Revenue"] == 90.0
    assert "2024-12-31" not in result["annual"]["income"]
    assert "Operating Income" not in result["annual"]["income"]["2025-12-31"]


def test_supplement_ignores_facts_from_failed_import(tmp_path):
    from agentcy.sec_statements import supplement_bundle

    conn = db.open_db(tmp_path)
    db.migrate(conn)
    conn.execute(
        "INSERT INTO sec_statement_import_run"
        " (archive_name,archive_hash,started_at,finished_at,status,fact_count)"
        " VALUES ('failed.zip','hash','2026-01-01','2026-01-02','FAILED',1)"
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO sec_statement_fact"
        " (import_run_id,accession,cik,filed_at,form,report_period,statement,"
        " taxonomy_tag,taxonomy_version,canonical_label,period_end,quarters,unit,"
        " value,source_hash,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, "0001", "0000000001", "2026-03-01", "10-K", "2025-12-31",
         "IS", "RevenueCustom", "issuer/2025", "Total Revenue", "2025-12-31", 4,
         "USD", 100.0, "failed-source", "2026-03-02"),
    )
    bundle = {
        "annual": {"income": {"2025-12-31": {}}, "balance": {}, "cashflow": {}},
        "quarterly": {"income": {}, "balance": {}, "cashflow": {}},
        "supplements": {"flows": {}, "points": {}},
    }

    supplement_bundle(conn, cik="1", as_of="2026-08-07", bundle=bundle)

    assert bundle["annual"]["income"]["2025-12-31"] == {}
