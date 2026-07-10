"""Stage-1 tiering (design §3): Core / Adjacent / Outside from FinanceDatabase
sector+industry. Tier is a priority LANE, orthogonal to grade — never blended.

RF10 — the Core/Adjacent industry lists are cross-checked against the ACTUAL
FinanceDatabase `industry` categoricals (a flat GICS-style set of 68 values), NOT an
invented yfinance-style sub-split taxonomy. Ground truth is a checked-in sample of the
real values extracted from the pinned `compression/equities.bz2` that
`scout.py:load_universe` reads (design §5): `tests/fixtures/financedatabase_categoricals.json`.
The fidelity test loads that sample and asserts every Core/Adjacent industry is a real
FinanceDatabase value — so a keyword that matches no real industry (leaving the Core lane
unreachable, the original RF10 failure) fails the suite.
"""
import json
from pathlib import Path

from agentcy import scout_grade as sg

_FIXTURE = Path(__file__).parent / "fixtures" / "financedatabase_categoricals.json"


def _real_categoricals():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return set(data["sectors"]), set(data["industries"])


# --- behaviour: real GICS-style industry values ---------------------------------------

def test_core_tier_from_real_industry():
    # 'Software' and 'Health Care Technology' are the actual FinanceDatabase industries the
    # owner's cloud/SaaS/AI + healthtech edge files under (MSFT/CRM/NOW/SNOW -> 'Software').
    assert sg.tier_of(sector="Information Technology", industry="Software") == "Core"
    assert sg.tier_of(sector="Health Care", industry="Health Care Technology") == "Core"


def test_adjacent_tier_from_real_industry():
    assert sg.tier_of(sector="Information Technology", industry="IT Services") == "Adjacent"
    assert (
        sg.tier_of(sector="Health Care", industry="Health Care Equipment & Supplies")
        == "Adjacent"
    )
    assert (
        sg.tier_of(
            sector="Information Technology",
            industry="Semiconductors & Semiconductor Equipment",
        )
        == "Adjacent"
    )


def test_outside_tier_default():
    assert sg.tier_of(sector="Energy", industry="Oil, Gas & Consumable Fuels") == "Outside"
    assert sg.tier_of(sector=None, industry=None) == "Outside"


def test_tier_is_case_insensitive():
    assert sg.tier_of(sector="information technology", industry="SOFTWARE") == "Core"
    assert sg.tier_of(sector="health care", industry="  it services  ") == "Adjacent"


def test_insurance_industry_is_not_core():
    # RF10 — the bare 'Insurance' industry is underwriting/distribution (the "Insurance
    # Brokers" trap), NOT insurance TECH. Insurtech surfaces via 'Software'. Never Core.
    assert sg.tier_of(sector="Financials", industry="Insurance") != "Core"


def test_health_care_providers_is_not_core():
    # Care-delivery / managed-care (UNH/VEEV-style filings) is Outside, not the healthtech
    # Core lane — only 'Health Care Technology' is Core on the real taxonomy.
    assert (
        sg.tier_of(sector="Health Care", industry="Health Care Providers & Services")
        == "Outside"
    )


# --- RF10 fidelity: every mapped industry is a REAL FinanceDatabase categorical ---------

def test_core_and_adjacent_industries_are_real_taxonomy_values():
    # The fidelity cross-check: load the checked-in sample of ACTUAL FinanceDatabase
    # industry values and assert every Core/Adjacent industry the code maps is one of them.
    # A vanity/mis-mapped value (e.g. 'software - infrastructure', 'medical devices') that
    # exists nowhere in the real taxonomy — the original RF10 failure that left Core
    # unreachable — fails here. Matching is exact (case-folded), as `tier_of` does.
    _sectors, real_industries = _real_categoricals()
    real_lower = {i.lower() for i in real_industries}
    for ind in sg._CORE_INDUSTRIES | sg._ADJACENT_INDUSTRIES:
        assert ind in real_lower, (
            f"mapped industry {ind!r} is not a real FinanceDatabase `industry` value "
            f"(RF10: the Core/Adjacent lanes must map to actual taxonomy rows)"
        )


def test_every_real_core_industry_reaches_core_lane():
    # Prove the Core lane is REACHABLE for real universe rows: every real industry the code
    # classes as Core must, fed verbatim (with its real casing), return "Core". Guards the
    # exact RF10 regression — Core silently unreachable for every stock in the universe.
    _sectors, real_industries = _real_categoricals()
    core_real = {i for i in real_industries if i.lower() in sg._CORE_INDUSTRIES}
    assert core_real, "no real FinanceDatabase industry maps to Core — Core lane unreachable"
    assert {"Software", "Health Care Technology"} <= core_real
    for ind in core_real:
        assert sg.tier_of(sector="Information Technology", industry=ind) == "Core"


def test_every_real_adjacent_industry_reaches_adjacent_lane():
    _sectors, real_industries = _real_categoricals()
    adj_real = {i for i in real_industries if i.lower() in sg._ADJACENT_INDUSTRIES}
    assert adj_real, "no real FinanceDatabase industry maps to Adjacent"
    for ind in adj_real:
        assert sg.tier_of(sector="Information Technology", industry=ind) == "Adjacent"


def test_core_and_adjacent_are_disjoint():
    assert not (sg._CORE_INDUSTRIES & sg._ADJACENT_INDUSTRIES)
