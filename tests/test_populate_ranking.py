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


def test_unknown_or_missing_band_sorts_last_stable_by_symbol():
    uni = _uni([
        ("Z", "mega_cap"),
        ("M", None),
        ("K", "micro_cap"),  # not a canonical band -> lowest priority
        ("A", ""),  # empty -> lowest priority
    ])
    # mega first; the three unknown/missing share the lowest priority, tie-broken by symbol
    assert populate.rank_universe(uni) == ["Z", "A", "K", "M"]


def test_starter_set_cuts_top_n_of_the_ranking():
    uni = _uni([(s, "large_cap") for s in ["D", "C", "B", "A", "E"]])
    assert populate.starter_set(uni, size=3) == ["A", "B", "C"]


def test_starter_set_size_larger_than_universe_returns_all_ranked():
    uni = _uni([("B", "mega_cap"), ("A", "small_cap")])
    assert populate.starter_set(uni, size=99) == ["B", "A"]
