"""Stage-1 Quality pillar raw metrics (design §1 Pillar Q): ROIC (Greenblatt),
gross-margin level+stability, owner-FCF margin.

RF7 — ROIC numerator is EBIT DIRECTLY (Greenblatt Magic Formula), not an invented
NOPAT/effective-tax-rate clamp. RF8 — gross-margin LEVEL + STABILITY are the two raw
ingredients of ONE Q leg (level percentile minus a bounded CV penalty); this raw-metric
layer exposes both so the scoring layer combines them into a single leg.
"""
import math
from datetime import datetime, timezone

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def _seed(conn, yf_statements, yf_series):
    store.store_statements(conn, "MSFT", yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, "MSFT", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_quality_metrics(tmp_db, yf_statements, yf_series):
    _seed(tmp_db, yf_statements, yf_series)
    q = sg.quality_metrics(tmp_db, "MSFT", as_of=AS_OF)
    assert q is not None
    # ROIC on the latest period (2026-03-31), RF7 — EBIT directly as the numerator:
    #   EBIT = 30.5e9 (NO NOPAT, NO tax clamp)
    #   denom = WorkingCapital 76e9 + (TotalAssets 550e9 - CurrentAssets 199e9 - Cash 84e9)
    #         = 76e9 + 267e9 = 343e9
    assert round(q["roic_pct"], 6) == round(100.0 * 30.5e9 / 343e9, 6)
    # gross margin level = mean over periods of GrossProfit/Revenue:
    #   45.5/66, 44/64, 42.5/62, 41/60 -> mean%
    gms = [45.5 / 66, 44 / 64, 42.5 / 62, 41 / 60]
    assert round(q["gross_margin_level_pct"], 6) == round(100.0 * (sum(gms) / 4), 6)
    # stability penalty = coefficient-of-variation of the gross-margin series (>=0, lower better)
    assert q["gross_margin_cv"] >= 0.0
    mean_gm = sum(gms) / 4
    pstdev = math.sqrt(sum((x - mean_gm) ** 2 for x in gms) / 4)
    assert round(q["gross_margin_cv"], 6) == round(pstdev / mean_gm, 6)
    # owner-FCF margin TTM = owner_fcf / revenue_ttm ; revenue_ttm = 66+64+62+60 = 252e9
    #   owner_fcf = 75.4e9 -> margin% = 100*75.4/252
    assert round(q["owner_fcf_margin_pct"], 6) == round(100.0 * 75.4e9 / 252e9, 6)


def test_quality_roic_uses_ebit_not_nopat(tmp_db, yf_statements, yf_series):
    """RF7 regression guard: the ROIC numerator is EBIT, so it must NOT match the old
    NOPAT-with-tax-clamp value (they differ because tax_rate = 4.7/30.5 > 0)."""
    _seed(tmp_db, yf_statements, yf_series)
    q = sg.quality_metrics(tmp_db, "MSFT", as_of=AS_OF)
    nopat = 30.5e9 * (1 - (4.7e9 / 30.5e9))
    nopat_roic = 100.0 * nopat / 343e9
    assert round(q["roic_pct"], 6) != round(nopat_roic, 6)
    assert round(q["roic_pct"], 6) == round(100.0 * 30.5e9 / 343e9, 6)


def test_quality_metrics_none_when_statements_absent(tmp_db):
    assert sg.quality_metrics(tmp_db, "MSFT", as_of=AS_OF) is None
