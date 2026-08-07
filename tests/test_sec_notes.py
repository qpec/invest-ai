import zipfile

from agentcy import db


def _archive(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "sub.tsv",
            "adsh\tcik\tname\tform\tperiod\tfiled\n"
            "0001-26-000001\t1\tAcme\t10-K\t20251231\t20260131\n",
        )
        archive.writestr(
            "ren.tsv",
            "adsh\treport\trfile\tmenucat\tshortname\tlongname\troleuri\tparentroleuri\tparentreport\tultparentrpt\n"
            "0001-26-000001\t7\tH\tN\tIncome Taxes\tDisclosure - Income Taxes\thttp://example/tax\t\t\t7\n",
        )
        archive.writestr(
            "pre.tsv",
            "adsh\treport\tline\tstmt\tinpth\ttag\tversion\tprole\tplabel\tnegating\n"
            "0001-26-000001\t7\t1\t\t0\tTaxCustom\tissuer/2025\tterseLabel\tIncome tax expense benefit\t0\n"
            "0001-26-000001\t7\t2\t\t0\tMystery\tissuer/2025\tterseLabel\tMystery subtotal\t0\n",
        )
        archive.writestr(
            "tag.tsv",
            "tag\tversion\tcustom\tabstract\tdatatype\tiord\tcrdr\ttlabel\tdoc\n"
            "TaxCustom\tissuer/2025\t1\t0\tmonetary\tD\tD\tIncome tax expense benefit\tTax expense\n"
            "Mystery\tissuer/2025\t1\t0\tmonetary\tD\tD\tMystery subtotal\tUnknown\n",
        )
        archive.writestr(
            "num.tsv",
            "adsh\ttag\tversion\tddate\tqtrs\tuom\tdimh\tiprx\tvalue\tfootnote\tfootlen\tdimn\tcoreg\tdurp\tdatp\tdcml\n"
            "0001-26-000001\tTaxCustom\tissuer/2025\t20251231\t4\tUSD\t0x00000000\t0\t10\t\t0\t0\t\t365\t0\t-6\n"
            "0001-26-000001\tTaxCustom\tissuer/2025\t20251231\t4\tUSD\t0x12345678\t0\t8\t\t0\t1\t\t365\t0\t-6\n"
            "0001-26-000001\tMystery\tissuer/2025\t20251231\t4\tUSD\t0x00000000\t0\t5\t\t0\t0\t\t365\t0\t-6\n",
        )


def test_notes_import_accepts_only_allowlisted_whole_entity_fact(tmp_path):
    from agentcy.sec_notes import import_archive

    archive = tmp_path / "2026_01_notes.zip"
    _archive(archive)
    conn = db.open_db(tmp_path / "state")
    db.migrate(conn)

    result = import_archive(
        conn, archive, eligible_ciks={"0000000001"}, imported_at="2026-02-01T00:00:00Z"
    )

    assert result == {"facts": 1, "status": "SUCCEEDED"}
    row = conn.execute("SELECT * FROM sec_notes_fact").fetchone()
    assert row["canonical_label"] == "Income Tax Expense"
    assert row["report_category"] == "N"
    assert row["value"] == 10.0


def test_notes_import_rejects_face_statements_and_non_filing_forms(tmp_path):
    from agentcy.sec_notes import allowed_form, allowed_report_category

    assert allowed_form("10-K")
    assert allowed_form("10-Q/A")
    assert not allowed_form("8-K")
    assert allowed_report_category("N")
    assert allowed_report_category("D")
    assert not allowed_report_category("S")
    assert not allowed_report_category("C")


def test_notes_supplement_fills_only_absent_series_on_existing_period(tmp_path):
    from agentcy.sec_notes import supplement_bundle

    archive = tmp_path / "2026_01_notes.zip"
    _archive(archive)
    conn = db.open_db(tmp_path / "state")
    db.migrate(conn)
    import_archive = __import__("agentcy.sec_notes", fromlist=["import_archive"]).import_archive
    import_archive(conn, archive, eligible_ciks={"0000000001"}, imported_at="2026-02-01")
    bundle = {
        "annual": {"income": {"2025-12-31": {"Total Revenue": 100.0}},
                   "balance": {}, "cashflow": {}},
        "quarterly": {"income": {}, "balance": {}, "cashflow": {}},
        "supplements": {"flows": {}, "points": {}},
    }

    result = supplement_bundle(conn, cik="1", as_of="2026-08-07", bundle=bundle)

    assert result["annual"]["income"]["2025-12-31"]["Total Revenue"] == 100.0
    assert result["supplements"]["flows"]["Income Tax Expense"]["annual"]["2025-12-31"] == 10.0
