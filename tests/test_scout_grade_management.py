"""Stage-1 Management pillar (design §1 Pillar M): share-count trend + accrual/cash
divergence. Qualitative half is deferred to Stage-2 (never faked). (Stage-1.5: per-share
owner-FCF growth moved to the Growth pillar G — see test_scout_grade_growth.py.)

RF6 — every share-dependent case seeds a MULTI-YEAR share series with a real ~1y-ago
baseline (index 2025-06-20, 2025-12-20, 2026-06-20; latest within 90d of as_of 2026-07-08)
so shares_yoy is actually computable (the recorded msft_shares_full fixture does NOT
satisfy that). A rising-share case proves the dilution signal actually surfaces.
"""
from datetime import datetime, timezone

import pandas as pd

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)

# RF6 baseline: latest 2026-06-20 within 90d of as_of; oldest 2025-06-20 is a real ~1y anchor.
SHARE_INDEX = pd.to_datetime(["2025-06-20", "2025-12-20", "2026-06-20"])


def _seed(conn, yf_statements, shares):
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, "MSFT",
                       pd.Series(shares, index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")


def test_management_metrics_shrinking_shares(tmp_db, yf_statements):
    # a shrinking share count ~1y apart (buyback signal) + a mid point
    _seed(tmp_db, yf_statements, [7.60e9, 7.50e9, 7.434e9])
    m = sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert m is not None
    # share-count trailing-12m growth is negative (buying back)
    assert m["shares_yoy_pct"] < 0
    # Stage-1.5 change 3: Sloan accruals = (net_income_ttm - Operating Cash Flow TTM),
    # normalized by revenue TTM (capex-independent earnings quality).
    #   NI_ttm = 25+24+23+22 = 94e9 ; OCF_ttm = 36+34+32+30 = 132e9 ; revenue = 252e9
    #   accrual% = 100 * (94 - 132) / 252 = negative (cash exceeds reported profit = clean)
    assert round(m["accrual_divergence_pct"], 3) == round(100.0 * (94e9 - 132e9) / 252e9, 3)


def test_management_metrics_rising_shares_flags_dilution(tmp_db, yf_statements):
    """RF6 — a rising-share case: serial issuance surfaces a POSITIVE shares_yoy_pct
    (the raw signal the M pillar's dilution leg / −15 penalty keys off downstream)."""
    _seed(tmp_db, yf_statements, [7.20e9, 7.40e9, 7.60e9])
    m = sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert m is not None
    # diluting: latest 7.60e9 vs ~1y-ago 7.20e9 => >5% issuance
    assert m["shares_yoy_pct"] > 5


def test_management_shares_leg_degrades_gracefully_without_baseline(tmp_db, yf_statements):
    """RF6 — with no ~1y-ago share observation the dilution leg SUSPENDS (shares_yoy_pct is
    None), it is not silently scored 0; the rest of the metric still computes."""
    store.store_statements(tmp_db, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    # only two observations, both recent (<1y apart) => no ~1y baseline for shares_yoy,
    # but >=2 observations so per-share growth still computes.
    store.store_shares(tmp_db, "MSFT", pd.Series(
        [7.50e9, 7.434e9], index=pd.to_datetime(["2026-04-20", "2026-06-20"])),
        fetched_at="2026-07-01T00:00:00Z")
    m = sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert m is not None
    assert m["shares_yoy_pct"] is None                    # leg suspended, not scored 0
    assert m["accrual_divergence_pct"] is not None        # rest of the metric intact


def test_management_none_when_absent(tmp_db):
    assert sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF) is None
