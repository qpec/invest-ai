from agentcy.security_master import (
    Eligibility,
    InstrumentType,
    classify,
    security_key,
)


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
