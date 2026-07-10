"""Stage-1 tiering (design §3): Core / Adjacent / Outside from FinanceDatabase
sector+industry. Tier is a priority LANE, orthogonal to grade — never blended.

RF10 — the Core/Adjacent keyword lists are cross-checked against the ACTUAL
FinanceDatabase (yfinance) sector/industry taxonomy and aligned to the design's
exact Core categories (cloud/SaaS infra, healthcare tech, insurance tech, AI
tooling). Mis-mapped entries such as "Insurance Brokers" (a distribution
industry, not insurtech) are NOT treated as Core.
"""
from agentcy import scout_grade as sg


def test_core_tier_from_industry():
    assert sg.tier_of(sector="Technology", industry="Software - Infrastructure") == "Core"
    assert sg.tier_of(sector="Healthcare", industry="Health Information Services") == "Core"


def test_adjacent_tier():
    assert sg.tier_of(sector="Technology", industry="Information Technology Services") == "Adjacent"
    assert sg.tier_of(sector="Healthcare", industry="Medical Devices") == "Adjacent"


def test_outside_tier_default():
    assert sg.tier_of(sector="Energy", industry="Oil & Gas E&P") == "Outside"
    assert sg.tier_of(sector=None, industry=None) == "Outside"


def test_tier_is_case_insensitive_on_keywords():
    assert sg.tier_of(sector="technology", industry="SOFTWARE - APPLICATION") == "Adjacent"


# --- RF10: real-taxonomy fidelity ------------------------------------------------------

def test_insurance_brokers_is_not_core():
    # RF10 — "Insurance Brokers" is a real FinanceDatabase industry, but it is DISTRIBUTION,
    # not insurance TECH. It must not be mis-mapped into the Core (insurtech) lane.
    assert sg.tier_of(sector="Financial Services", industry="Insurance Brokers") != "Core"


def test_core_keywords_are_real_taxonomy_values():
    # RF10 — every Core keyword must be a substring of an actual FinanceDatabase/yfinance
    # industry value (no invented taxonomy leaking a false Core promotion). "cloud" /
    # "ai tooling" style vanity keywords that match NO real industry are disallowed.
    real_industries = {
        "software - infrastructure", "software - application",
        "information technology services", "semiconductors",
        "semiconductor equipment & materials", "communication equipment",
        "computer hardware", "consumer electronics", "electronic components",
        "scientific & technical instruments", "solar",
        "health information services", "medical devices",
        "medical instruments & supplies", "diagnostics & research",
        "drug manufacturers - general", "drug manufacturers - specialty & generic",
        "biotechnology", "medical care facilities", "healthcare plans",
        "pharmaceutical retailers", "medical distribution",
        "insurance - property & casualty", "insurance - life",
        "insurance - diversified", "insurance - specialty",
        "insurance - reinsurance", "insurance brokers", "credit services",
        "capital markets", "asset management", "banks - regional",
        "banks - diversified", "financial data & stock exchanges",
        "oil & gas e&p",
    }
    for kw in sg._CORE_INDUSTRY_KEYWORDS + sg._ADJACENT_INDUSTRY_KEYWORDS:
        assert any(kw in ind for ind in real_industries), (
            f"keyword {kw!r} matches no real FinanceDatabase industry value")


def test_core_checked_before_adjacent():
    # "Software - Infrastructure" contains the bare Adjacent keyword "software"; Core must
    # win (checked first) so an infra name is never demoted to Adjacent.
    assert sg.tier_of(sector="Technology", industry="Software - Infrastructure") == "Core"


def test_semiconductors_taxonomy_spelling_is_adjacent():
    # The real taxonomy value is plural "Semiconductors" (not "Semiconductor").
    assert sg.tier_of(sector="Technology", industry="Semiconductors") == "Adjacent"
