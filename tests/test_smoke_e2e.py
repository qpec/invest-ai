"""P8.13 golden end-to-end: the whole pipeline on one seeded thesis, no domain fakes.
Only fetch/yf is redirected to the recorded fixtures (tests never touch the network,
per conftest). Proves: daily run -> archived letter matches golden + one queued outbox row.

Reconciliations applied (authoritative over the plan skeleton):
  * R1 — the run is driven through cli.main(["run","daily"]) -> jobs.daily.main, which
    opens its OWN connection on AGENTCY_STATE_DIR (tmp_path) and fires the S2 ping itself.
  * The daily sweep runs EVERY due key (14-day lookback); to get exactly one on-time
    letter + one outbox row we pre-finish every earlier due day (the P6 test convention,
    tests/test_jobs_daily.py::_finish_prior_daily_keys), leaving 2026-07-08 as the sole
    on-time key.
  * The yf door returns the NORMALIZED frame [close, adj_close, dividend, currency] that
    the real fetch_daily_bars produces, so real store.store_price_bars is exercised.
  * The daily loop fetches only fetch_daily_bars (prices + FX) — statements/officers/
    calendar belong to the weekly/quarterly/event lanes, so no other yf stub is needed.
"""
from datetime import datetime, timezone

import pytest

from agentcy import db, mirror, register, runlog
from agentcy.clock import FixedClock
from agentcy.mirror import PositionIn, SnapshotIn


@pytest.fixture()
def seeded(tmp_db, monkeypatch, yf_fixture):
    """One held MSFT position with a live intact thesis (one moat-linked automated trigger
    + one prompted trigger), one snapshot, prices from the msft_history/eurusd fixtures.
    Every daily due day before 2026-07-08 is pre-finished so the sweep has exactly one
    on-time key. Returns (conn, clock)."""
    clock = FixedClock(datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc))
    conn = tmp_db

    # redirect the ONLY yfinance door to the recorded fixtures (store/fetch stay real):
    import agentcy.fetch.yf as yf
    monkeypatch.setattr(yf, "fetch_daily_bars",
                        lambda t, *, state_dir, period="10d": _frame(yf_fixture(_hist_for(t))))

    # journal-FK anchor for the thesis version, then create + activate the thesis:
    je = db.append_journal_entry(conn, {
        "ts": db.to_iso(clock.now()), "decision_type": "gate_verdict",
        "decision_subtype": "buy_ready", "ticker": "MSFT", "actor": "owner",
        "reasoning_at_the_moment": "seed"})
    tid = register.create_thesis(conn, ticker="MSFT", origin="gate",
                                 fields=_msft_fields(), triggers=_msft_triggers(),
                                 journal_ref=je, clock=clock)
    register.activate(conn, tid, cause="seed snapshot", clock=clock)

    snap = SnapshotIn(as_of=db.to_iso(clock.now()), source="manual_entry", cash_balance_eur=8000.0,
                      positions=(PositionIn(symbol="MSFT", yf_ticker="MSFT", instrument_type="stock",
                                            quantity=40, avg_open_price=300.0, native_currency="USD",
                                            mv_native=18000.0, mv_eur=16500.0, weight=0.67, leverage=1.0),))
    mirror.ingest_snapshot(conn, snap, clock=clock)
    _finish_prior_daily_keys(conn, clock, keep="2026-07-08")
    conn.commit()
    return conn, clock


def test_daily_run_archives_letter_and_enqueues_one_outbox_row(seeded, monkeypatch, golden):
    from agentcy import cli
    conn, clock = seeded
    monkeypatch.setattr(cli, "_open", lambda: conn)
    monkeypatch.setattr(cli, "_clock", lambda: clock)
    monkeypatch.setattr("agentcy.deadman.ping", lambda conn: True)   # no network in the ping either

    assert cli.main(["run", "daily"]) == 0

    # (a) exactly one queued daily letter in the outbox
    queued = db.fetch_outbox_queued(conn)
    dailies = [r for r in queued if r["kind"] == "daily"]
    assert len(dailies) == 1
    assert dailies[0]["payload_html"]           # non-empty rendered letter

    # (b) the archived markdown letter byte-matches the golden (record once with UPDATE_GOLDEN=1)
    reports = db.fetch_reports(conn, type="daily")
    assert len(reports) == 1
    golden("smoke_daily.md.txt", reports[0]["content_md"])

    # (c) a finished daily run_log row for the scheduled key
    run = db.fetch_run(conn, "daily", clock_scheduled_for(clock))
    assert run is not None and run["finished_at"] is not None and run["status"] in ("ok", "degraded")


# --- fixture helpers (kept tiny; real render/store logic is exercised, not mocked) ---
def clock_scheduled_for(clock):
    return clock.now().date().isoformat()


def _finish_prior_daily_keys(conn, clock, keep):
    """Steady state: every earlier due day already ran, so today's sweep has exactly one
    on-time key (the P6 convention, tests/test_jobs_daily.py). Without this the 14-day
    lookback would archive a letter + enqueue an outbox row for all 14 due days."""
    for key in runlog.due_keys("daily", as_of=clock.now()):
        if key == keep:
            continue
        h = runlog.start(conn, "daily", key, clock=clock)
        runlog.finish(conn, h.run_id, status="ok", outputs={"kind": "pulse"}, clock=clock)


def _hist_for(t):
    return "eurusd_fx" if t.endswith("EUR=X") else "msft_history"


def _frame(js):
    """Recorded raw yfinance frame -> the normalized frame real fetch_daily_bars returns:
    DatetimeIndex, columns exactly [close, adj_close, dividend, currency]."""
    import pandas as pd
    raw = pd.DataFrame(js["data"], index=pd.to_datetime(js["index"]), columns=js["columns"])
    out = pd.DataFrame({
        "close": raw["Close"].astype(float),
        "adj_close": raw["Adj Close"].astype(float),
        "dividend": raw["Dividends"].fillna(0.0).astype(float),
    }, index=raw.index)
    out["currency"] = str(js["currency"])
    return out


def _msft_fields():
    """Minimal valid ThesisFields (A.1): 2-sentence model, one enumerated moat, a fair band,
    and the FR9 enum/statement fields."""
    return register.ThesisFields(
        business_model_2s="Sells cloud infrastructure on subscription. Enterprise switching costs are the moat.",
        moat_types=("switching_costs",), moat_evidence="multi-year enterprise agreements",
        owner_earnings_json='{"fcf_ttm": 8.0e10}', owner_earnings_narrative="strong owner FCF",
        value_at_purchase=30.0, fair_band_low=25.0, fair_band_high=35.0,
        denominator_note=None, conviction="high", mgmt_trust="trusted_professional",
        mgmt_trust_note=None, circle_fit="core", circle_fit_note=None,
        ten_year_statement="Cloud consolidation runs a decade and the data moat compounds.",
        status_buy_flag=False, status_buy_note=None)


def _msft_triggers():
    """Two triggers (A.1 requires 2-5): one moat-linked automated growth_floor + one prompted."""
    return [
        register.TriggerSpec(
            type="growth_floor",
            statement="If revenue growth TTM < 5% for 2 consecutive quarters, the moat is eroding.",
            metric="revenue_growth_ttm", comparator="<", threshold=5.0,
            moat_link="switching_costs", persistence="2_consecutive_quarters"),
        register.TriggerSpec(
            type="owner_attested_event",
            statement="Has the CEO departed or announced departure?",
            metric=None, comparator=None, threshold=None, moat_link=None,
            persistence="single_observation", yes_means="fire"),
    ]
