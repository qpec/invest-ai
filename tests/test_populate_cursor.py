"""Coverage derivation + nightly cursor (populator design 4/6, plan notes 3/4/5)."""
from datetime import datetime, timezone

import pandas as pd

from agentcy import db, populate
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed_full(conn, sym, yf_statements, yf_series, *, price_date="2026-07-07"):
    """A fully-cached name: >=4 periods x3 statements + a shares obs + a fresh price bar."""
    store.store_statements(conn, sym, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-07T00:00:00Z")
    store.store_shares(conn, sym, yf_series("msft_shares_full"),
                       fetched_at="2026-07-07T00:00:00Z")
    frame = pd.DataFrame(
        {"close": [500.0], "adj_close": [500.0], "dividend": [0.0], "currency": ["USD"]},
        index=pd.to_datetime([price_date]))
    store.store_price_bars(conn, sym, frame, run_id=None, fetched_at="2026-07-07T00:00:00Z")


def test_is_cached_true_only_when_all_coverage_present(tmp_db, yf_statements, yf_series):
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    assert populate.is_cached(tmp_db, "MSFT", as_of=AS_OF) is True
    # a name with only income statements is NOT cached
    store.store_statements(tmp_db, "THIN",
                           {"income": yf_statements("msft_statements")["income"]},
                           run_id=None, fetched_at="2026-07-07T00:00:00Z")
    assert populate.is_cached(tmp_db, "THIN", as_of=AS_OF) is False
    assert populate.is_cached(tmp_db, "NONE", as_of=AS_OF) is False


def test_next_targets_never_attempted_first_in_rank_order(tmp_db, yf_statements, yf_series):
    ranked = ["MSFT", "VEEV", "AAPL"]
    # none attempted, none cached -> all three, in rank order, cut to budget
    targets = populate.next_targets(tmp_db, ranked, budget=2, as_of=AS_OF)
    assert targets == ["MSFT", "VEEV"]


def test_next_targets_skips_cached_fresh_names(tmp_db, yf_statements, yf_series):
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    db.append_universe_fetch(tmp_db, yf_ticker="MSFT", outcome="ok",
                             attempted_at="2026-07-07T00:00:00Z", run_id=None)
    ranked = ["MSFT", "VEEV"]
    # MSFT is cached + fresh -> not a target; VEEV never attempted -> the only target
    assert populate.next_targets(tmp_db, ranked, budget=10, as_of=AS_OF) == ["VEEV"]


def test_next_targets_excludes_dead_listed_names(tmp_db):
    ranked = ["DEAD", "LIVE"]
    for _ in range(3):
        db.append_universe_fetch(tmp_db, yf_ticker="DEAD", outcome="failed",
                                 attempted_at="2026-07-01T00:00:00Z", run_id=None)
    # DEAD has 3 failures (>= threshold) and its last attempt is recent -> excluded.
    targets = populate.next_targets(tmp_db, ranked, budget=10, as_of=AS_OF,
                                    dead_after_failures=3)
    assert targets == ["LIVE"]


def test_dead_listed_name_reeligible_after_90_days(tmp_db):
    ranked = ["DEAD"]
    for _ in range(3):
        db.append_universe_fetch(tmp_db, yf_ticker="DEAD", outcome="failed",
                                 attempted_at="2026-01-01T00:00:00Z", run_id=None)
    # last attempt 2026-01-01 is > 90 days before AS_OF (2026-07-08) -> re-eligible.
    targets = populate.next_targets(tmp_db, ranked, budget=10, as_of=AS_OF,
                                    dead_after_failures=3)
    assert targets == ["DEAD"]
