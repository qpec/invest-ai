"""Task 6: persist position_detail rows during ingest_snapshot.

Fetch (api_pull, with details) -> ingest -> position_detail rows land.
CSV/manual snapshots (no details) write ZERO detail rows and produce identical deltas.
"""
from agentcy import db, mirror
from agentcy.clock import SystemClock
from agentcy.fetch import etoro


# fake FX: USD->EUR at 0.9, everything else 1:1. Deterministic, no network.
_FX = lambda amount, ccy: amount * 0.9 if ccy == "USD" else amount


def _fake_client():
    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "AAPL", "type": "Stocks", "units": 2.0, "invested": 400.0,
                 "open_rate": 200.0, "open_date": "2024-06-01", "mv_native": 500.0,
                 "pnl_native": 100.0, "leverage": 1.0, "currency": "USD"},
                {"symbol": "AAPL", "type": "Stocks", "units": 1.0, "invested": 200.0,
                 "open_rate": 200.0, "open_date": "2023-01-15", "mv_native": 250.0,
                 "pnl_native": 50.0, "leverage": 1.0, "currency": "USD"},
            ]
        def get_balances(self):
            return {"cash": 100.0, "currency": "USD"}
    return FakeClient()


def test_ingest_persists_position_detail_rows(tmp_db):
    snap = etoro.fetch_etoro_snapshot(_fake_client(), fx=_FX, as_of="2026-07-10")
    snapshot_id, _deltas = mirror.ingest_snapshot(tmp_db, snap, clock=SystemClock())
    rows = db.fetch_position_details(tmp_db, snapshot_id)
    assert len(rows) == 1                        # two AAPL lots collapse to one detail row
    (row,) = rows
    assert row["symbol"] == "AAPL"
    assert row["opened_at"] == "2023-01-15"      # earliest lot
    assert row["lot_count"] == 2
    assert row["invested_eur"] == 540.0          # (400+200) native USD * 0.9


def test_csv_snapshot_writes_zero_detail_rows(tmp_db):
    csv_text = (
        "symbol,instrument_type,quantity,avg_open_price,native_currency,"
        "market_value_native,market_value_eur,leverage\n"
        "VEEV,stock,10,200.0,USD,2500.0,2300.0,1.0\n"
        "CASH,cash,0,0,EUR,300.0,300.0,1.0\n"
    )
    snap = mirror.parse_etoro_csv(csv_text)
    assert snap.details == ()                     # CSV path never builds details
    snapshot_id, deltas = mirror.ingest_snapshot(tmp_db, snap, clock=SystemClock())
    assert db.fetch_position_details(tmp_db, snapshot_id) == []
    assert [d.kind for d in deltas] == []         # baseline: nothing to reconcile


def test_manual_snapshot_writes_zero_detail_rows(tmp_db):
    snap = mirror.parse_manual_text("cash: 300\nVEEV 10 2300 USD\n")
    assert snap.details == ()
    snapshot_id, deltas = mirror.ingest_snapshot(tmp_db, snap, clock=SystemClock())
    assert db.fetch_position_details(tmp_db, snapshot_id) == []
    assert [d.kind for d in deltas] == []


def _leveraged_client():
    """A FakeClient with ONE leveraged (2x) SPY stock lot — trips the Hell-No tripwire."""
    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY", "type": "Stocks", "units": 3.0, "invested": 600.0,
                 "open_rate": 200.0, "open_date": "2024-06-01", "mv_native": 720.0,
                 "pnl_native": 120.0, "leverage": 2.0, "currency": "USD"},
            ]
        def get_balances(self):
            return {"cash": 100.0, "currency": "USD"}
    return FakeClient()


def test_leveraged_etoro_snapshot_fires_hellno_tripwire_end_to_end(tmp_db):
    """Charter-critical: a leveraged eToro pull flows fetch -> ingest -> Hell-No leverage
    tripwire NOTICE, end-to-end and network-free (FakeClient + injected fx)."""
    clock = SystemClock()
    snap = etoro.fetch_etoro_snapshot(_leveraged_client(), fx=_FX, as_of="2026-07-10")

    # 1) ingest reconciles the leveraged position into a leverage_violation Delta.
    snapshot_id, deltas = mirror.ingest_snapshot(tmp_db, snap, clock=clock)
    lev = [d for d in deltas if d.kind == "leverage_violation" and d.symbol == "SPY"]
    assert len(lev) == 1
    assert lev[0].new_value == 2.0

    # 2) minting enqueues the Hell-No leverage tripwire notice with the exact dedupe_key.
    mirror.mint_reconciliation_asks(tmp_db, snapshot_id, deltas, clock=clock)
    row = db.fetch_outbox_by_key(tmp_db, f"leverage:{snapshot_id}:SPY")
    assert row is not None
    assert row["kind"] == "notice"
    assert "Hell-No leverage tripwire" in row["payload_html"]
    assert "SPY" in row["payload_html"]
