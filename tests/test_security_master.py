from agentcy.security_master import (
    Eligibility,
    InstrumentType,
    classify,
    security_key,
)

import csv
import json

import pytest


@pytest.fixture
def universe_csv(tmp_path):
    path = tmp_path / "universe.csv"
    rows = [
        ["ACME", "Acme Corporation", "Technology", "Software", "United States",
         "Large Cap", "NMS", "USD"],
        ["FUND", "Example Municipal Income Fund", "", "", "United States", "",
         "NYSE", "USD"],
        ["0AAA.L", "Acme Corporation", "Technology", "Software", "United States",
         "Large Cap", "LSE", "USD"],
        ["DUTCH.AS", "Dutch Systems N.V.", "Technology", "Software", "Netherlands",
         "Mid Cap", "AMS", "EUR"],
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "name", "sector", "industry", "country", "market_cap",
                         "exchange", "currency"])
        writer.writerows(rows)
    return path


@pytest.fixture
def sec_exchange_json(tmp_path):
    path = tmp_path / "company_tickers_exchange.json"
    path.write_text(json.dumps({
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [1, "Acme Corporation", "ACME", "Nasdaq"],
            [2, "Example Municipal Income Fund", "FUND", "NYSE"],
        ],
    }), encoding="utf-8")
    return path


def test_primary_sec_ordinary_share_is_eligible():
    result = classify(
        symbol="ACME",
        name="Acme Corporation",
        country="United States",
        exchange="Nasdaq",
        cik="0000000001",
        sec_primary=True,
    )
    assert result.instrument_type is InstrumentType.ORDINARY_SHARE
    assert result.eligibility is Eligibility.ELIGIBLE
    assert result.reason_code == "PRIMARY_ORDINARY_SHARE"


def test_closed_end_fund_is_ineligible():
    result = classify(
        symbol="FUND",
        name="Example Municipal Income Fund",
        country="United States",
        exchange="NYSE",
        cik="0000000002",
        sec_primary=True,
    )
    assert result.instrument_type is InstrumentType.FUND
    assert result.eligibility is Eligibility.INELIGIBLE
    assert result.reason_code == "FUND"


def test_listed_bond_is_ineligible_before_ordinary_share_rule():
    result = classify(
        symbol="ENJ",
        name="Entergy First Mortgage Bonds 5.0% Series due 2052",
        country="United States",
        exchange="NYSE",
        cik="0000000003",
        sec_primary=True,
    )
    assert result.instrument_type is InstrumentType.LISTED_DEBT
    assert result.reason_code == "LISTED_DEBT"


def test_foreign_secondary_for_us_issuer_requires_review():
    result = classify(
        symbol="0AAA.L",
        name="Acme Corporation",
        country="United States",
        exchange="LSE",
        cik=None,
        sec_primary=False,
    )
    assert result.eligibility is Eligibility.REVIEW
    assert result.reason_code == "UNRESOLVED_SECONDARY_LISTING"


def test_dutch_amsterdam_ordinary_share_is_eligible():
    result = classify(
        symbol="ACME.AS",
        name="Acme N.V.",
        country="Netherlands",
        exchange="AMS",
        cik=None,
        sec_primary=False,
    )
    assert result.eligibility is Eligibility.ELIGIBLE
    assert result.reason_code == "DUTCH_PRIMARY_ORDINARY_SHARE"


def test_warrant_unit_preferred_and_royalty_trust_are_ineligible():
    cases = [
        ("ACMEW", "Acme Warrants", InstrumentType.WARRANT_OR_UNIT, "WARRANT_OR_UNIT"),
        ("ACMEU", "Acme Units", InstrumentType.WARRANT_OR_UNIT, "WARRANT_OR_UNIT"),
        ("ACME-P", "Acme 6% Preferred Stock", InstrumentType.PREFERRED_SHARE,
         "PREFERRED_SHARE"),
        ("PBT", "Permian Basin Royalty Trust", InstrumentType.ROYALTY_TRUST,
         "ROYALTY_TRUST"),
    ]
    for symbol, name, instrument_type, reason in cases:
        result = classify(symbol=symbol, name=name, country="United States",
                          exchange="NYSE", cik="1", sec_primary=True)
        assert result.instrument_type is instrument_type
        assert result.eligibility is Eligibility.INELIGIBLE
        assert result.reason_code == reason


def test_exchange_style_preferred_and_debt_labels_are_ineligible():
    cases = [
        ("LILAP", "Issuer 9% Cumulative Preference Shares",
         InstrumentType.PREFERRED_SHARE, "PREFERRED_SHARE"),
        ("CTA-PA", "Issuer USD 4.50 Cum Pfd Registered Shs",
         InstrumentType.PREFERRED_SHARE, "PREFERRED_SHARE"),
        ("JSM", "Issuer SR NT 6% 121543",
         InstrumentType.LISTED_DEBT, "LISTED_DEBT"),
    ]
    for symbol, name, instrument_type, reason in cases:
        result = classify(symbol=symbol, name=name, country="United States",
                          exchange="Nasdaq", cik="1", sec_primary=True)
        assert result.instrument_type is instrument_type
        assert result.eligibility is Eligibility.INELIGIBLE
        assert result.reason_code == reason


def test_operating_company_with_trust_in_name_is_not_assumed_royalty_trust():
    result = classify(symbol="TRST", name="TrustCo Bank Corp NY",
                      country="United States", exchange="Nasdaq", cik="4",
                      sec_primary=True)
    assert result.instrument_type is InstrumentType.ORDINARY_SHARE
    assert result.eligibility is Eligibility.ELIGIBLE


def test_unknown_unmatched_instrument_requires_review():
    result = classify(symbol="MYST", name="Mystery Holdings", country="",
                      exchange="", cik=None, sec_primary=False)
    assert result.instrument_type is InstrumentType.UNKNOWN
    assert result.eligibility is Eligibility.REVIEW
    assert result.reason_code == "UNKNOWN_INSTRUMENT"


def test_security_key_prefers_zero_padded_cik():
    assert security_key(cik="123", normalized_name="acme", primary_symbol="ACME") == (
        "cik:0000000123"
    )


def test_security_key_without_cik_is_deterministic_and_name_based():
    first = security_key(cik=None, normalized_name="acme nv", primary_symbol="ACME.AS")
    second = security_key(cik=None, normalized_name="acme nv", primary_symbol="OTHER")
    assert first == second
    assert first.startswith("name:")


def test_import_promotes_only_complete_run(tmp_db, universe_csv, sec_exchange_json):
    from agentcy.security_master import import_snapshot

    summary = import_snapshot(
        tmp_db,
        universe_csv,
        sec_exchange_json,
        source_vintage="2026-08-07",
        observed_at="2026-08-07T08:00:00Z",
    )
    assert summary.input_rows == 4
    assert summary.eligible == 2
    assert summary.ineligible == 1
    assert summary.review == 1
    assert tmp_db.execute("SELECT COUNT(*) FROM v_current_security").fetchone()[0] == 4


def test_exact_snapshot_replay_is_idempotent(tmp_db, universe_csv, sec_exchange_json):
    from agentcy.security_master import import_snapshot

    kwargs = dict(source_vintage="2026-08-07", observed_at="2026-08-07T08:00:00Z")
    first = import_snapshot(tmp_db, universe_csv, sec_exchange_json, **kwargs)
    second = import_snapshot(tmp_db, universe_csv, sec_exchange_json, **kwargs)
    assert second.run_id == first.run_id
    assert tmp_db.execute("SELECT COUNT(*) FROM security_master_run").fetchone()[0] == 1
    assert tmp_db.execute("SELECT COUNT(*) FROM security_observation").fetchone()[0] == 4


def test_import_writes_provider_aliases(tmp_db, universe_csv, sec_exchange_json):
    from agentcy.security_master import import_snapshot

    import_snapshot(tmp_db, universe_csv, sec_exchange_json,
                    source_vintage="2026-08-07",
                    observed_at="2026-08-07T08:00:00Z")
    aliases = tmp_db.execute(
        "SELECT provider, symbol, security_key FROM security_alias ORDER BY symbol"
    ).fetchall()
    assert len(aliases) == 4
    assert aliases[1]["symbol"] == "ACME"
    assert aliases[1]["security_key"] == "cik:0000000001"


def test_import_retains_listing_currency(tmp_db, universe_csv, sec_exchange_json):
    from agentcy.security_master import import_snapshot

    import_snapshot(tmp_db, universe_csv, sec_exchange_json,
                    source_vintage="2026-08-07",
                    observed_at="2026-08-07T08:00:00Z")
    row = tmp_db.execute(
        "SELECT currency FROM v_current_security WHERE symbol='DUTCH.AS'"
    ).fetchone()
    assert row["currency"] == "EUR"


def test_import_keeps_stale_ticker_collision_in_review(tmp_db, tmp_path):
    from agentcy.security_master import import_snapshot

    universe = tmp_path / "universe.csv"
    universe.write_text(
        "symbol,name,sector,industry,country,market_cap,exchange,currency\n"
        "MSTR,Strategy Inc,Tech,,United States,,NMS,USD\n"
        "STRC,Sarcos Technology and Robotics Corporation Common Stock,Tech,,"
        "United States,,NMS,USD\n",
        encoding="utf-8",
    )
    sec = tmp_path / "sec.json"
    sec.write_text(json.dumps({
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [1050446, "Strategy Inc", "MSTR", "Nasdaq"],
            [1050446, "Strategy Inc", "STRC", "Nasdaq"],
        ],
    }), encoding="utf-8")
    import_snapshot(tmp_db, universe, sec, source_vintage="2026-08-07",
                    observed_at="2026-08-07T08:00:00Z")
    row = tmp_db.execute(
        "SELECT * FROM v_current_security WHERE symbol='STRC'"
    ).fetchone()
    assert row["eligibility"] == "REVIEW"
    assert row["reason_code"] == "IDENTITY_CONFLICT"


def test_audit_summary_reports_reason_and_exchange_counts(
        tmp_db, universe_csv, sec_exchange_json):
    from agentcy.security_master import audit_summary, import_snapshot

    import_snapshot(tmp_db, universe_csv, sec_exchange_json,
                    source_vintage="2026-08-07",
                    observed_at="2026-08-07T08:00:00Z")
    audit = audit_summary(tmp_db)
    assert audit["input_rows"] == 4
    assert audit["reasons"]["PRIMARY_ORDINARY_SHARE"] == 1
    assert audit["reasons"]["UNRESOLVED_SECONDARY_LISTING"] == 1
    assert audit["exchanges"]["AMS"] == 1
