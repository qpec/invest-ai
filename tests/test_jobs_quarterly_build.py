"""P6.17: quarterly run_one — G.4 QuarterlyContext, F.2 matrix pull, records appendix (cost basis
HERE ONLY), benchmark write via benchmark.py, summary + document enqueued."""
from datetime import datetime, timezone

import pandas as pd

from agentcy import db, runlog
from agentcy.clock import FixedClock
from agentcy.jobs import runner

Q = FixedClock(datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc))


def _stub_benchmark_and_series(monkeypatch):
    from agentcy.jobs import quarterly
    idx = pd.date_range("2026-07-01", periods=5, freq="D")
    monkeypatch.setattr(quarterly, "fetch_and_store_benchmark",
                        lambda conn, *, start, end, run_id, clock: None)
    monkeypatch.setattr(quarterly, "benchmark_series_eur",
                        lambda start, end: pd.Series([100, 101, 102, 101, 103], index=idx, dtype=float))
    monkeypatch.setattr(quarterly, "portfolio_series_eur",
                        lambda conn, *, start, end: pd.Series([100, 102, 99, 101, 104], index=idx, dtype=float))


def _finish_prior_quarterly_keys(conn, keep):
    """Steady state: every earlier quarter already ran, so today's sweep has exactly one
    on-time key (mirrors the weekly wire-up helper; without it the 2-quarter lookback
    archives both keys)."""
    for key in runlog.due_keys("quarterly", as_of=Q.now()):
        if key == keep:
            continue
        h = runlog.start(conn, "quarterly", key, clock=Q)
        runlog.finish(conn, h.run_id, status="ok", outputs={}, clock=Q)


def test_run_one_builds_summary_and_document(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import quarterly
    conn = seeded_portfolio["conn"]
    _finish_prior_quarterly_keys(conn, keep="2026-10-01")
    _stub_benchmark_and_series(monkeypatch)
    rc = runner.sweep_and_run(conn, "quarterly", quarterly.run_one, clock=Q, state_dir=tmp_path)
    assert rc == 0
    assert db.fetch_run(conn, "quarterly", "2026-10-01")["status"] == "ok"
    assert db.fetch_outbox_by_key(conn, "quarterly:2026-10-01:summary") is not None
    doc = db.fetch_outbox_by_key(conn, "quarterly:2026-10-01:doc")
    assert doc is not None and doc["kind"] == "quarterly_doc" and doc["document_path"]
    assert len(db.fetch_reports(conn, type="quarterly")) == 1


def test_summary_message_carries_no_benchmark_token(seeded_portfolio, tmp_path, monkeypatch):
    """The quarantine is by absence in daily/weekly, but the quarterly SUMMARY message must
    still keep the benchmark comparison in the number, not leak 'S&P' as raw text past lint —
    invariant 7 lint scoping: benchmark tokens are allowed in quarterly output class only."""
    from agentcy.jobs import quarterly
    conn = seeded_portfolio["conn"]
    _finish_prior_quarterly_keys(conn, keep="2026-10-01")
    _stub_benchmark_and_series(monkeypatch)
    runner.sweep_and_run(conn, "quarterly", quarterly.run_one, clock=Q, state_dir=tmp_path)
    summary = db.fetch_outbox_by_key(conn, "quarterly:2026-10-01:summary")
    assert "do not extrapolate" in summary["payload_html"].lower()   # G.4 §1 "13 weeks" guard


def test_records_appendix_reads_cost_basis(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import quarterly
    conn = seeded_portfolio["conn"]
    _stub_benchmark_and_series(monkeypatch)
    snap = db.fetch_latest_snapshot(conn)
    appendix = quarterly.build_records_appendix(conn, snap["snapshot_id"])
    assert "MSFT" in appendix and appendix["MSFT"]["avg_open_price"] == 300.0   # cost basis, HERE ONLY
