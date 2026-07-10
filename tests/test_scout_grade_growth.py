"""Stage-1.5 Growth pillar G (design change 3): annualized revenue growth + per-share
NORMALIZED owner-earnings growth, EACH leg ROIC-gated (leg * min(1, ROIC/15%)); thin data
degrades to neutral 50.0 (unknown != punished). Per-share growth moved here from M.
"""
from datetime import datetime, timezone

import pandas as pd

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
SHARE_INDEX = pd.to_datetime(["2025-06-20", "2025-12-20", "2026-06-20"])


def test_growth_leg_score_gates_on_roic():
    """A leg at/above 15% ROIC keeps its full percentile; below 15% it is discounted by
    min(1, ROIC/15). Mirrors roic_leg_score's floor factor."""
    pop = [10.0, 20.0, 30.0, 40.0]
    pct = sg.sector_percentile(30.0, pop, higher_better=True)
    assert sg.growth_leg_score(30.0, pop, roic_pct=20.0) == pct           # ROIC>=15 -> full
    assert sg.growth_leg_score(30.0, pop, roic_pct=7.5) == round(pct * 0.5, 6)  # 7.5/15
    assert sg.growth_leg_score(30.0, pop, roic_pct=0.0) == 0.0            # non-positive ROIC


def test_growth_metrics_revenue_and_per_share_present(tmp_db, yf_statements):
    """Revenue growth annualized over the archive window; per-share NORMALIZED owner-FCF
    growth over the share window; both labelled with the <3yr caveat."""
    store.store_statements(tmp_db, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT",
                       pd.Series([7.60e9, 7.50e9, 7.434e9], index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")
    g = sg.growth_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert g is not None
    # revenue rose oldest->newest (60 -> 66 e9) so annualized revenue growth is positive
    assert g["revenue_growth_pct"] is not None and g["revenue_growth_pct"] > 0
    assert "3yr CAGR not computable" in g["revenue_growth_label"]
    # per-share normalized owner-FCF growth present (shrinking shares -> positive)
    assert g["per_share_ofcf_growth_pct"] is not None and g["per_share_ofcf_growth_pct"] > 0
    assert "3yr CAGR not computable" in g["per_share_ofcf_growth_label"]


def test_growth_metrics_thin_returns_none_legs(tmp_db, yf_statements):
    """One income period + one share observation -> neither leg computable -> both None
    (the pillar-scoring layer degrades G to neutral 50; Task 5)."""
    store.store_statements(tmp_db, "MSFT",
                           {"income": yf_statements("msft_statements")["income"].iloc[:, :1]},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT",
                       pd.Series([7.5e9], index=pd.to_datetime(["2026-06-20"])),
                       fetched_at="2026-07-01T00:00:00Z")
    g = sg.growth_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert g is not None
    assert g["revenue_growth_pct"] is None
    assert g["per_share_ofcf_growth_pct"] is None


def test_management_no_longer_carries_per_share_growth(tmp_db, yf_statements):
    """Stage-1.5: per-share owner-FCF growth is MOVED to G; M no longer exposes it."""
    store.store_statements(tmp_db, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "MSFT",
                       pd.Series([7.60e9, 7.50e9, 7.434e9], index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")
    m = sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert m is not None
    assert "per_share_ofcf_growth_pct" not in m
    assert "shares_yoy_pct" in m and "accrual_divergence_pct" in m
