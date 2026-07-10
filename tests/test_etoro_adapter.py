"""Task 4: pure-function tests for the eToro adapter.

instrument-type mapping + per-symbol lot aggregation. No I/O, no network.
"""
import json

import pytest

from agentcy.fetch import etoro


# fake FX: USD->EUR at 0.9, everything else 1:1. Deterministic, no network.
_FX = lambda amount, ccy: amount * 0.9 if ccy == "USD" else amount


# -- map_instrument_type -----------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Stocks", "stock"),
        ("stock", "stock"),
        ("STOCK", "stock"),
        ("ETF", "etf"),
        ("etfs", "etf"),
        ("Crypto", "crypto"),
        ("cryptocurrencies", "crypto"),
        ("CryptoCurrency", "crypto"),
        ("CopyPortfolio", "copyportfolio"),
        ("copyportfolios", "copyportfolio"),
        ("  Stocks  ", "stock"),  # trimmed
    ],
)
def test_map_instrument_type_maps_taxonomy(raw, expected):
    assert etoro.map_instrument_type(raw) == expected


def test_map_instrument_type_unknown_raises():
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.map_instrument_type("bond")
    assert "unknown eToro instrument type" in str(exc.value)
    assert "'bond'" in str(exc.value)


def test_map_instrument_type_empty_raises():
    with pytest.raises(etoro.EtoroError):
        etoro.map_instrument_type("")
    with pytest.raises(etoro.EtoroError):
        etoro.map_instrument_type("   ")


# -- aggregate_lots ----------------------------------------------------------
def test_aggregate_lots_collapses_symbol():
    lots = [
        {"units": 2.0, "invested": 400.0, "open_rate": 200.0, "open_date": "2024-06-01",
         "mv_native": 500.0, "pnl_native": 100.0, "leverage": 1.0},
        {"units": 1.0, "invested": 210.0, "open_rate": 210.0, "open_date": "2023-01-15",
         "mv_native": 250.0, "pnl_native": 40.0, "leverage": 1.0},
    ]
    agg = etoro.aggregate_lots("AAPL", lots)
    assert agg["symbol"] == "AAPL"
    assert agg["quantity"] == 3.0
    assert agg["invested_native"] == 610.0
    assert agg["opened_at"] == "2023-01-15"
    assert agg["lot_count"] == 2
    assert round(agg["avg_open_price"], 6) == round(610.0 / 3.0, 6)
    assert agg["mv_native"] == 750.0
    assert agg["pnl_native"] == 140.0
    assert agg["leverage"] == 1.0


def test_aggregate_lots_single_lot():
    lots = [
        {"units": 5.0, "invested": 1000.0, "open_rate": 200.0, "open_date": "2025-03-10",
         "mv_native": 1100.0, "pnl_native": 100.0, "leverage": 1.0},
    ]
    agg = etoro.aggregate_lots("MSFT", lots)
    assert agg["symbol"] == "MSFT"
    assert agg["quantity"] == 5.0
    assert agg["invested_native"] == 1000.0
    assert agg["opened_at"] == "2025-03-10"
    assert agg["lot_count"] == 1
    assert agg["avg_open_price"] == 200.0
    assert agg["mv_native"] == 1100.0
    assert agg["pnl_native"] == 100.0
    assert agg["leverage"] == 1.0


def test_aggregate_lots_opened_at_is_earliest_regardless_of_order():
    lots = [
        {"units": 1.0, "invested": 100.0, "open_rate": 100.0, "open_date": "2025-03-10",
         "mv_native": 110.0, "pnl_native": 10.0, "leverage": 1.0},
        {"units": 1.0, "invested": 100.0, "open_rate": 100.0, "open_date": "2022-11-01",
         "mv_native": 120.0, "pnl_native": 20.0, "leverage": 1.0},   # earliest, in the middle
        {"units": 1.0, "invested": 100.0, "open_rate": 100.0, "open_date": "2024-07-22",
         "mv_native": 130.0, "pnl_native": 30.0, "leverage": 1.0},
    ]
    agg = etoro.aggregate_lots("MSFT", lots)
    assert agg["opened_at"] == "2022-11-01"
    assert agg["lot_count"] == 3


def test_aggregate_lots_leverage_is_max():
    lots = [
        {"units": 1.0, "invested": 100.0, "open_rate": 100.0, "open_date": "2024-01-01",
         "mv_native": 120.0, "pnl_native": 20.0, "leverage": 1.0},
        {"units": 1.0, "invested": 100.0, "open_rate": 100.0, "open_date": "2024-02-01",
         "mv_native": 130.0, "pnl_native": 30.0, "leverage": 2.0},
    ]
    agg = etoro.aggregate_lots("TSLA", lots)
    assert agg["leverage"] == 2.0


def test_aggregate_lots_leverage_defaults_to_one():
    lots = [
        {"units": 1.0, "invested": 100.0, "open_rate": 100.0, "open_date": "2024-01-01",
         "mv_native": 120.0, "pnl_native": 20.0},  # no leverage key
    ]
    agg = etoro.aggregate_lots("NVDA", lots)
    assert agg["leverage"] == 1.0


def test_aggregate_lots_zero_quantity_avg_price_none():
    lots = [
        {"units": 0.0, "invested": 0.0, "open_rate": 0.0, "open_date": "2024-01-01",
         "mv_native": 0.0, "pnl_native": 0.0, "leverage": 1.0},
    ]
    agg = etoro.aggregate_lots("ZERO", lots)
    assert agg["quantity"] == 0.0
    assert agg["avg_open_price"] is None


# -- fetch_etoro_snapshot (Task 5) -------------------------------------------
def test_fetch_etoro_snapshot_builds_snapshotin_and_details():
    class FakeClient:
        def get_positions(self):
            return [{"symbol": "AAPL", "type": "Stocks", "units": 3.0, "invested": 600.0,
                     "open_rate": 200.0, "open_date": "2023-01-15", "mv_native": 750.0,
                     "pnl_native": 150.0, "leverage": 1.0, "currency": "USD"}]
        def get_balances(self):
            return {"cash": 100.0, "currency": "USD"}
    snap = etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")
    assert snap.source == "api_pull"
    assert snap.cash_balance_eur == 90.0
    (p,) = snap.positions
    assert p.symbol == "AAPL" and p.instrument_type == "stock" and p.quantity == 3.0
    assert p.mv_eur == 675.0 and p.native_currency == "USD"
    assert p.yf_ticker == "AAPL"
    assert p.weight == 1.0  # single position => whole invested MV
    (d,) = snap.details
    assert d.symbol == "AAPL" and d.opened_at == "2023-01-15" and d.lot_count == 1
    assert d.invested_eur == 540.0
    assert d.invested_native == 600.0
    assert d.unrealized_pnl_native == 150.0
    assert d.unrealized_pnl_pct == pytest.approx(25.0)  # 150/600*100
    # raw_json round-trips the original lot dicts for the symbol
    assert json.loads(d.raw_json)[0]["symbol"] == "AAPL"


def test_fetch_etoro_snapshot_multi_lot_collapses_to_one():
    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "MSFT", "type": "Stocks", "units": 2.0, "invested": 400.0,
                 "open_rate": 200.0, "open_date": "2024-06-01", "mv_native": 500.0,
                 "pnl_native": 100.0, "leverage": 1.0, "currency": "EUR"},
                {"symbol": "MSFT", "type": "Stocks", "units": 1.0, "invested": 210.0,
                 "open_rate": 210.0, "open_date": "2023-01-15", "mv_native": 250.0,
                 "pnl_native": 40.0, "leverage": 1.0, "currency": "EUR"},
            ]
        def get_balances(self):
            return {"cash": 0.0, "currency": "EUR"}
    snap = etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")
    (p,) = snap.positions
    assert p.symbol == "MSFT" and p.quantity == 3.0
    assert p.mv_native == 750.0 and p.mv_eur == 750.0  # EUR: 1:1
    (d,) = snap.details
    assert d.lot_count == 2
    assert d.opened_at == "2023-01-15"  # earliest lot
    assert d.invested_native == 610.0
    assert len(json.loads(d.raw_json)) == 2


def test_fetch_etoro_snapshot_folds_cash_position():
    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "AAPL", "type": "Stocks", "units": 1.0, "invested": 100.0,
                 "open_rate": 100.0, "open_date": "2024-01-01", "mv_native": 110.0,
                 "pnl_native": 10.0, "leverage": 1.0, "currency": "EUR"},
                {"symbol": "CASH", "type": "cash", "units": 0.0, "invested": 0.0,
                 "open_rate": 0.0, "open_date": "2024-01-01", "mv_native": 50.0,
                 "pnl_native": 0.0, "leverage": 1.0, "currency": "EUR"},
            ]
        def get_balances(self):
            return {"cash": 50.0, "currency": "EUR"}
    snap = etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")
    # the cash entry is NOT an instrument
    assert [p.symbol for p in snap.positions] == ["AAPL"]
    assert [d.symbol for d in snap.details] == ["AAPL"]
    # cash comes from balances, not the folded position
    assert snap.cash_balance_eur == 50.0


def test_fetch_etoro_snapshot_shape_guard_rejects_non_list():
    class FakeClient:
        def get_positions(self):
            return {"unexpected": "dict body"}
        def get_balances(self):
            return {"cash": 0.0, "currency": "EUR"}
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")
    assert "expected a list of positions" in str(exc.value)
    assert "dict" in str(exc.value)


def test_fetch_etoro_snapshot_shape_guard_rejects_non_dict_element():
    class FakeClient:
        def get_positions(self):
            return ["AAPL"]  # str, not a dict
        def get_balances(self):
            return {"cash": 0.0, "currency": "EUR"}
    with pytest.raises(etoro.EtoroError):
        etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")


def test_fetch_etoro_snapshot_unknown_type_propagates():
    class FakeClient:
        def get_positions(self):
            return [{"symbol": "GOLD", "type": "Commodities", "units": 1.0, "invested": 100.0,
                     "open_rate": 100.0, "open_date": "2024-01-01", "mv_native": 110.0,
                     "pnl_native": 10.0, "leverage": 1.0, "currency": "USD"}]
        def get_balances(self):
            return {"cash": 0.0, "currency": "EUR"}
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")
    assert "unknown eToro instrument type" in str(exc.value)


def test_fetch_etoro_snapshot_captures_optional_detail_fields():
    class FakeClient:
        def get_positions(self):
            return [{"symbol": "AAPL", "type": "Stocks", "units": 1.0, "invested": 100.0,
                     "open_rate": 100.0, "open_date": "2024-01-01", "mv_native": 120.0,
                     "pnl_native": 20.0, "leverage": 1.0, "currency": "USD",
                     "current_rate": 120.0, "direction": "buy"}]
        def get_balances(self):
            return {"cash": 0.0, "currency": "EUR"}
    snap = etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")
    (d,) = snap.details
    assert d.current_rate == 120.0
    assert d.direction == "buy"


def test_fetch_etoro_snapshot_converts_per_symbol_currency():
    # Two symbols in different native currencies: USD must be crossed (×0.9),
    # EUR must pass through untouched. Guards against per-symbol FX crosswiring.
    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "AAPL", "type": "Stocks", "units": 1.0, "invested": 100.0,
                 "open_rate": 100.0, "open_date": "2024-01-01", "mv_native": 200.0,
                 "pnl_native": 100.0, "leverage": 1.0, "currency": "USD"},
                {"symbol": "ASML", "type": "Stocks", "units": 1.0, "invested": 100.0,
                 "open_rate": 100.0, "open_date": "2024-01-01", "mv_native": 300.0,
                 "pnl_native": 200.0, "leverage": 1.0, "currency": "EUR"},
            ]
        def get_balances(self):
            return {"cash": 0.0, "currency": "EUR"}
    snap = etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")
    by_symbol = {p.symbol: p for p in snap.positions}
    assert by_symbol["AAPL"].native_currency == "USD"
    assert by_symbol["AAPL"].mv_eur == 180.0  # 200 × 0.9
    assert by_symbol["ASML"].native_currency == "EUR"
    assert by_symbol["ASML"].mv_eur == 300.0  # EUR: unchanged


def test_fetch_etoro_snapshot_zero_invested_none_branches():
    # A closed-to-zero remnant: units and invested both 0 reaches the adapter.
    # Covers BOTH None branches through fetch_etoro_snapshot (not aggregate_lots
    # directly): avg_open_price None (units==0) and unrealized_pnl_pct None
    # (invested_native==0).
    class FakeClient:
        def get_positions(self):
            return [{"symbol": "AAPL", "type": "Stocks", "units": 0.0, "invested": 0.0,
                     "open_rate": 0.0, "open_date": "2024-01-01", "mv_native": 0.0,
                     "pnl_native": 0.0, "leverage": 1.0, "currency": "USD"}]
        def get_balances(self):
            return {"cash": 0.0, "currency": "EUR"}
    snap = etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")
    (p,) = snap.positions
    assert p.avg_open_price is None
    (d,) = snap.details
    assert d.unrealized_pnl_pct is None


def test_fetch_etoro_snapshot_missing_symbol_raises():
    class FakeClient:
        def get_positions(self):
            return [{"type": "Stocks", "units": 1.0, "invested": 100.0,
                     "open_rate": 100.0, "open_date": "2024-01-01", "mv_native": 120.0,
                     "pnl_native": 20.0, "leverage": 1.0, "currency": "USD"}]  # no symbol
        def get_balances(self):
            return {"cash": 0.0, "currency": "EUR"}
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.fetch_etoro_snapshot(FakeClient(), fx=_FX, as_of="2026-07-10")
    assert "position missing symbol" in str(exc.value)
