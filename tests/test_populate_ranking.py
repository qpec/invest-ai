"""Universe liquidity ranking + starter-set cut (populator design 2, plan note 1).
Pure functions over the universe DataFrame - no DB, no network."""
import pandas as pd

from agentcy import populate


def _uni(rows):
    return pd.DataFrame(rows, columns=["symbol", "market_cap"])


def test_ranks_bands_mega_large_mid_small_then_symbol():
    uni = _uni([
        ("DELTA", "small_cap"),
        ("BRAVO", "mega_cap"),
        ("CHARLIE", "large_cap"),
        ("ALPHA", "mega_cap"),
        ("ECHO", "mid_cap"),
    ])
    assert populate.rank_universe(uni) == ["ALPHA", "BRAVO", "CHARLIE", "ECHO", "DELTA"]


def test_band_match_is_case_and_whitespace_insensitive():
    uni = _uni([("A", " Mega_Cap "), ("B", "LARGE_CAP")])
    assert populate.rank_universe(uni) == ["A", "B"]


def test_real_financedatabase_band_labels_rank_correctly():
    """The live FinanceDatabase equities.bz2 uses title-case, space-separated bands
    ('Mega Cap', 'Large Cap', 'Mid Cap', 'Small Cap', 'Micro Cap', 'Nano Cap') - NOT the
    underscore form the test fixtures used. Normalization must map both to the same key,
    else every real name falls to unknown and the liquidity ordering collapses."""
    uni = _uni([
        ("SMALL", "Small Cap"),
        ("MEGA", "Mega Cap"),
        ("MICRO", "Micro Cap"),   # below the >=$300M floor -> unknown bucket, last
        ("LARGE", "Large Cap"),
        ("MID", "Mid Cap"),
        ("NANO", "Nano Cap"),     # unknown bucket, last (tie-broken by symbol)
    ])
    assert populate.rank_universe(uni) == ["MEGA", "LARGE", "MID", "SMALL", "MICRO", "NANO"]


def test_unknown_or_missing_band_sorts_last_stable_by_symbol():
    uni = _uni([
        ("Z", "mega_cap"),
        ("M", None),
        ("K", "micro_cap"),  # not a canonical band -> lowest priority
        ("A", ""),  # empty -> lowest priority
    ])
    # mega first; the three unknown/missing share the lowest priority, tie-broken by symbol
    assert populate.rank_universe(uni) == ["Z", "A", "K", "M"]


def test_filter_us_eu_keeps_home_listings_drops_cross_listings_and_non_us_eu():
    """US+EU companies are kept ONLY on their home exchange; foreign cross-listings of the same
    company (AAPL.MI on Milan, ASML on NMS) and non-US/EU domiciles are dropped."""
    uni = pd.DataFrame(
        [("AAPL", "United States", "NMS"),        # US home -> keep
         ("AAPL.MI", "United States", "MIL"),      # Apple cross-listed on Milan -> drop
         ("SAP.DE", "Germany", "GER"),             # German home (XETRA) -> keep
         ("SAP.F", "Germany", "FRA"),              # SAP on Frankfurt regional -> drop
         ("ASML.AS", "Netherlands", "AMS"),        # Dutch home -> keep
         ("ASML", "Netherlands", "NMS"),           # ASML US listing -> drop (not home)
         ("MC.PA", "France", "PAR"),               # French home -> keep
         ("SHOP.TO", "Canada", "TOR"),             # Canada -> drop (not US/EU)
         ("005930.KS", "South Korea", "KSC")],     # Korea -> drop
        columns=["symbol", "country", "exchange"])
    kept = set(populate.filter_us_eu(uni)["symbol"])
    assert kept == {"AAPL", "SAP.DE", "ASML.AS", "MC.PA"}


def test_filter_us_eu_passes_through_when_columns_absent():
    """Hand-built universes (grading tests, the tier tests) lack country/exchange columns and
    must pass through unchanged so grading/ranking on them is unaffected."""
    uni = _uni([("A", "mega_cap"), ("B", "small_cap")])
    assert list(populate.filter_us_eu(uni)["symbol"]) == ["A", "B"]


def test_starter_set_cuts_top_n_of_the_ranking():
    uni = _uni([(s, "large_cap") for s in ["D", "C", "B", "A", "E"]])
    assert populate.starter_set(uni, size=3) == ["A", "B", "C"]


def test_starter_set_size_larger_than_universe_returns_all_ranked():
    uni = _uni([("B", "mega_cap"), ("A", "small_cap")])
    assert populate.starter_set(uni, size=99) == ["B", "A"]
