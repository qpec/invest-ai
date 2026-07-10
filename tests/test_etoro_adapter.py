"""Task 4: pure-function tests for the eToro adapter.

instrument-type mapping + per-symbol lot aggregation. No I/O, no network.
"""
import pytest

from agentcy.fetch import etoro


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
