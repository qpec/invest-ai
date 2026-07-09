"""tests/test_store_derivations.py — P3 store derivations over the append-only archive."""
from datetime import datetime, timezone

from agentcy import db
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def test_revenue_yoy_series_from_archive(tmp_db):
    # four consecutive quarters of Total Revenue -> two YoY points (needs 4 quarters for 2 YoY pairs)
    for pe, rev in [("2025-06-30", 100.0), ("2025-09-30", 105.0),
                    ("2026-03-31", 120.0), ("2026-06-30", 130.0)]:
        db.append_fundamentals_period(tmp_db, yf_ticker="VEEV", statement_type="income",
            period_end=pe, payload_json=f'{{"Total Revenue": {rev}}}', fingerprint=pe,
            fetched_at="2026-07-08T00:00:00Z", run_id=None)
    s = store.revenue_yoy_series(tmp_db, "VEEV", as_of=AS_OF)
    assert s.usable()
    latest_pe, latest_val = s.value[-1]
    assert latest_pe == "2026-06-30" and round(latest_val, 1) == 30.0   # 130 vs 100 YoY
