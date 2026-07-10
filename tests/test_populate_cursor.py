"""Coverage derivation + nightly cursor (populator design 4/6, plan notes 3/4/5)."""
from datetime import datetime, timezone

import pandas as pd

from agentcy import db, populate
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed_full(conn, sym, yf_statements, yf_series, *, price_date="2026-07-07",
               statements=None):
    """A fully-cached name: >=4 periods x3 statements + a shares obs + a fresh price bar.
    Pass ``statements`` to override the recorded pack (e.g. old period_ends for STALE)."""
    store.store_statements(conn, sym, statements or yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-07T00:00:00Z")
    store.store_shares(conn, sym, yf_series("msft_shares_full"),
                       fetched_at="2026-07-07T00:00:00Z")
    frame = pd.DataFrame(
        {"close": [500.0], "adj_close": [500.0], "dividend": [0.0], "currency": ["USD"]},
        index=pd.to_datetime([price_date]))
    store.store_price_bars(conn, sym, frame, run_id=None, fetched_at="2026-07-07T00:00:00Z")


def _stale_statements(yf_statements):
    """The recorded pack with its period columns shifted back to >135 days before AS_OF,
    so coverage still holds (>=4 periods x3 statements) but statement_history reads STALE
    (newest period_end past STATEMENT_MAX_AGE_DAYS with no calendar) — plan note 4."""
    pack = yf_statements("msft_statements")
    # newest 2025-06-30 is 373 days before AS_OF (2026-07-08); well past the 135-day fallback
    old_cols = pd.to_datetime(["2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"])
    return {stype: frame.set_axis(old_cols, axis="columns") for stype, frame in pack.items()}


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


def test_next_targets_stale_refresh_after_never_oldest_first(tmp_db, yf_statements, yf_series):
    """The second cursor tier (plan note 4): covered-but-STALE names refresh least-recently
    first, and strictly AFTER every never-attempted name."""
    stale = _stale_statements(yf_statements)
    # two covered names whose income statements are STALE, with different last_attempt stamps
    _seed_full(tmp_db, "OLD", yf_statements, yf_series, statements=stale)
    _seed_full(tmp_db, "NEW", yf_statements, yf_series, statements=stale)
    db.append_universe_fetch(tmp_db, yf_ticker="OLD", outcome="ok",
                             attempted_at="2026-01-01T00:00:00Z", run_id=None)
    db.append_universe_fetch(tmp_db, yf_ticker="NEW", outcome="ok",
                             attempted_at="2026-05-01T00:00:00Z", run_id=None)
    # sanity: both are covered (is_cached) yet STALE-covered (refresh-eligible)
    assert populate.is_cached(tmp_db, "OLD", as_of=AS_OF) is True
    assert populate._is_stale_covered(tmp_db, "OLD", as_of=AS_OF) is True
    # NEVER never-attempted; OLD/NEW are the refresh tier -> after NEVER, oldest last_attempt first
    ranked = ["NEW", "OLD", "NEVER"]
    assert populate.next_targets(tmp_db, ranked, budget=10, as_of=AS_OF) == ["NEVER", "OLD", "NEW"]


def test_next_targets_retry_attempted_but_uncovered_ranks_as_work(tmp_db, yf_statements, yf_series):
    """The retry branch (populate.py:99-100): a name attempted before but not yet fully
    covered is treated as first-tier work, in liquidity-rank order among never-attempted."""
    # RETRY was attempted (a failed row) but nothing archived -> not is_cached
    db.append_universe_fetch(tmp_db, yf_ticker="RETRY", outcome="no_data",
                             attempted_at="2026-07-06T00:00:00Z", run_id=None)
    ranked = ["FRESHNAME", "RETRY", "OTHER"]
    # all three are work (RETRY attempted-but-uncovered, the others never-attempted); rank order
    assert populate.next_targets(tmp_db, ranked, budget=10, as_of=AS_OF) == \
        ["FRESHNAME", "RETRY", "OTHER"]


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
