"""Stage-1 Management pillar (design §1 Pillar M): share-count trend, per-share owner-FCF
growth, accrual/cash divergence. Qualitative half is deferred to Stage-2 (never faked).

RF6 — every share-dependent case seeds a MULTI-YEAR share series with a real ~1y-ago
baseline (index 2025-06-20, 2025-12-20, 2026-06-20; latest within 90d of as_of 2026-07-08)
so shares_yoy is actually computable (the recorded msft_shares_full fixture does NOT
satisfy that). A rising-share case proves the dilution signal actually surfaces.
RF11 — the per-share owner-FCF metric is labelled honestly (only a <3yr window exists in
the archive) so it is never presented as a true 3yr CAGR.
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
    # accrual/cash divergence = (net_income_ttm - owner_fcf_ttm), normalized by revenue TTM.
    #   NI_ttm = 25+24+23+22 = 94e9 ; owner_fcf = 75.4e9 ; revenue = 252e9 ; >0 = accruals
    assert round(m["accrual_divergence_pct"], 3) == round(100.0 * (94e9 - 75.4e9) / 252e9, 3)
    # per-share owner-FCF growth is present (>= 2 share observations)
    assert m["per_share_ofcf_growth_pct"] is not None
    # shrinking shares on a constant owner-FCF base => per-share growth is POSITIVE
    assert m["per_share_ofcf_growth_pct"] > 0


def test_management_per_share_growth_labelled_honestly(tmp_db, yf_statements):
    """RF11 — only a <3yr window exists in the archive, so the metric must be labelled as
    the annualized available-window growth, never presented as a true 3yr CAGR."""
    _seed(tmp_db, yf_statements, [7.60e9, 7.50e9, 7.434e9])
    m = sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert m is not None
    label = m["per_share_ofcf_growth_label"]
    assert "3yr CAGR not computable" in label
    # honest label names the actual window used (oldest -> newest share observation).
    assert "2025-06-20" in label and "2026-06-20" in label


def test_management_metrics_rising_shares_flags_dilution(tmp_db, yf_statements):
    """RF6 — a rising-share case: serial issuance surfaces a POSITIVE shares_yoy_pct
    (the raw signal the M pillar's dilution leg / −15 penalty keys off downstream)."""
    _seed(tmp_db, yf_statements, [7.20e9, 7.40e9, 7.60e9])
    m = sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert m is not None
    # diluting: latest 7.60e9 vs ~1y-ago 7.20e9 => >5% issuance
    assert m["shares_yoy_pct"] > 5
    # per-share owner-FCF growth on a rising share base (constant owner-FCF) is NEGATIVE
    assert m["per_share_ofcf_growth_pct"] < 0


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
    assert m["per_share_ofcf_growth_pct"] is not None


def test_management_none_when_absent(tmp_db):
    assert sg.management_metrics(tmp_db, "MSFT", as_of=AS_OF) is None
