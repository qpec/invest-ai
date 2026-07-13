"""Pure-function + adapter tests for the eToro client against the REAL API contract.

instrument-type mapping (numeric instrumentTypeID), per-instrument lot aggregation,
and fetch_etoro_snapshot driven by a sanitized recorded fixture. No I/O, no network:
a FakeClient replays the fixture JSON so the real parser runs offline.
"""
import json
from pathlib import Path

import pytest

from agentcy.fetch import etoro

FIXTURES = Path(__file__).parent / "fixtures" / "etoro"


def _load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


# fake FX: USD->EUR at 0.9, everything else 1:1. Deterministic, no network.
_FX = lambda amount, ccy: amount * 0.9 if ccy == "USD" else amount


class FixtureClient:
    """Replays the sanitized portfolio.json / instruments.json fixtures.

    Mirrors the real EtoroClient surface (get_portfolio / get_instruments) so the
    real fetch_etoro_snapshot parser runs against recorded field names offline.
    """

    def __init__(self, portfolio=None, instruments=None):
        self._portfolio = portfolio if portfolio is not None else _load("portfolio")
        self._instruments = instruments if instruments is not None else _load("instruments")
        self.instrument_calls = []

    def get_portfolio(self):
        return self._portfolio

    def get_instruments(self, ids):
        self.instrument_calls.append(list(ids))
        wanted = {int(i) for i in ids}
        return [row for row in self._instruments["instrumentDisplayDatas"]
                if row["instrumentID"] in wanted]


# -- map_instrument_type (numeric instrumentTypeID) --------------------------
@pytest.mark.parametrize("type_id,expected", [
    (5, "stock"),
    (6, "etf"),
    ("5", "stock"),
    ("6", "etf"),
])
def test_map_instrument_type_maps_known_ids(type_id, expected):
    assert etoro.map_instrument_type(type_id) == expected


@pytest.mark.parametrize("type_id", [7, 99, None, "", "bond"])
def test_map_instrument_type_unknown_defaults_to_stock(type_id):
    # Best-effort default: an unknown/missing instrumentTypeID must not crash the pull.
    assert etoro.map_instrument_type(type_id) == "stock"


# -- aggregate_lots (real position-object field names) -----------------------
def _lot(**kw):
    base = {"units": 1.0, "amount": 100.0, "openRate": 100.0,
            "openDateTime": "2024-01-01T00:00:00.000Z", "isBuy": True, "leverage": 1.0}
    base.update(kw)
    return base


def test_aggregate_lots_collapses_instrument():
    lots = [
        _lot(units=2.0, amount=400.0, openDateTime="2024-06-01T00:00:00.000Z"),
        _lot(units=1.0, amount=210.0, openDateTime="2023-01-15T00:00:00.000Z"),
    ]
    agg = etoro.aggregate_lots("AAPL", lots)
    assert agg["symbol"] == "AAPL"
    assert agg["quantity"] == 3.0
    assert agg["invested_native"] == 610.0
    assert agg["mv_native"] == 610.0                 # no live MV -> invested is the native value
    assert agg["opened_at"] == "2023-01-15T00:00:00.000Z"
    assert agg["lot_count"] == 2
    assert round(agg["avg_open_price"], 6) == round(610.0 / 3.0, 6)
    assert agg["leverage"] == 1.0
    assert agg["direction"] == "buy"


def test_aggregate_lots_opened_at_is_earliest_regardless_of_order():
    lots = [
        _lot(openDateTime="2025-03-10T00:00:00.000Z"),
        _lot(openDateTime="2022-11-01T00:00:00.000Z"),   # earliest, in the middle
        _lot(openDateTime="2024-07-22T00:00:00.000Z"),
    ]
    agg = etoro.aggregate_lots("MSFT", lots)
    assert agg["opened_at"] == "2022-11-01T00:00:00.000Z"
    assert agg["lot_count"] == 3


def test_aggregate_lots_leverage_is_max():
    lots = [_lot(leverage=1.0), _lot(leverage=2.0)]
    assert etoro.aggregate_lots("TSLA", lots)["leverage"] == 2.0


def test_aggregate_lots_leverage_defaults_to_one():
    lot = _lot()
    del lot["leverage"]
    assert etoro.aggregate_lots("NVDA", [lot])["leverage"] == 1.0


def test_aggregate_lots_zero_quantity_avg_price_none():
    agg = etoro.aggregate_lots("ZERO", [_lot(units=0.0, amount=0.0)])
    assert agg["quantity"] == 0.0
    assert agg["avg_open_price"] is None


def test_aggregate_lots_direction_from_is_buy():
    assert etoro.aggregate_lots("SHRT", [_lot(isBuy=False)])["direction"] == "sell"


# -- fetch_etoro_snapshot (fixture-driven) -----------------------------------
def test_snapshot_maps_instrument_ids_to_tickers_and_types():
    snap = etoro.fetch_etoro_snapshot(FixtureClient(), fx=_FX, as_of="2026-07-13")
    by_symbol = {p.symbol: p for p in snap.positions}
    assert set(by_symbol) == {"SPY", "SHOP"}
    assert by_symbol["SPY"].instrument_type == "etf"       # instrumentTypeID 6
    assert by_symbol["SHOP"].instrument_type == "stock"    # instrumentTypeID 5
    assert by_symbol["SPY"].yf_ticker == "SPY"
    assert by_symbol["SHOP"].yf_ticker == "SHOP"


def test_snapshot_collapses_three_spy_lots_to_one_position():
    snap = etoro.fetch_etoro_snapshot(FixtureClient(), fx=_FX, as_of="2026-07-13")
    by_symbol = {p.symbol: p for p in snap.positions}
    spy = by_symbol["SPY"]
    # 3 SPY lots: units 0.274449 + 0.5 + 0.1 ; amount 200.9 + 350.0 + 75.0
    assert spy.quantity == pytest.approx(0.874449)
    assert spy.mv_native == pytest.approx(625.9)           # sum of amounts (native USD)
    assert spy.mv_eur == pytest.approx(625.9 * 0.9)        # crossed to EUR
    assert spy.native_currency == "USD"
    details = {d.symbol: d for d in snap.details}
    d = details["SPY"]
    assert d.lot_count == 3
    assert d.opened_at == "2026-03-02T10:15:00.000Z"       # earliest of the 3 lots
    assert d.invested_native == pytest.approx(625.9)
    assert d.invested_eur == pytest.approx(625.9 * 0.9)
    assert d.direction == "buy"
    assert len(json.loads(d.raw_json)) == 3


def test_snapshot_single_shop_lot():
    snap = etoro.fetch_etoro_snapshot(FixtureClient(), fx=_FX, as_of="2026-07-13")
    shop = {p.symbol: p for p in snap.positions}["SHOP"]
    assert shop.quantity == 4.0
    assert shop.mv_native == pytest.approx(250.0)
    assert shop.avg_open_price == pytest.approx(62.5)      # 250 / 4
    d = {d.symbol: d for d in snap.details}["SHOP"]
    assert d.lot_count == 1
    assert d.opened_at == "2026-04-11T13:45:12.000Z"


def test_snapshot_cash_from_credit():
    snap = etoro.fetch_etoro_snapshot(FixtureClient(), fx=_FX, as_of="2026-07-13")
    # clientPortfolio.credit 2857.0 USD * 0.9 -> EUR
    assert snap.cash_balance_eur == pytest.approx(2857.0 * 0.9)
    assert snap.source == "api_pull"


def test_snapshot_pnl_fields_are_none_no_live_mv_in_payload():
    snap = etoro.fetch_etoro_snapshot(FixtureClient(), fx=_FX, as_of="2026-07-13")
    for d in snap.details:
        assert d.unrealized_pnl_native is None
        assert d.unrealized_pnl_pct is None


def test_snapshot_fetches_metadata_for_distinct_instrument_ids_once():
    client = FixtureClient()
    etoro.fetch_etoro_snapshot(client, fx=_FX, as_of="2026-07-13")
    # exactly one get_instruments call, for the two distinct ids
    assert len(client.instrument_calls) == 1
    assert sorted(client.instrument_calls[0]) == [3000, 4148]


def test_snapshot_direction_short_from_is_buy_false():
    portfolio = {"clientPortfolio": {"credit": 0.0, "positions": [
        {"instrumentID": 3000, "units": 1.0, "amount": 100.0, "openRate": 100.0,
         "openDateTime": "2024-01-01T00:00:00.000Z", "isBuy": False, "leverage": 1.0}]}}
    snap = etoro.fetch_etoro_snapshot(FixtureClient(portfolio=portfolio), fx=_FX, as_of="2026-07-13")
    assert snap.details[0].direction == "sell"


def test_snapshot_leveraged_lot_flows_through():
    portfolio = {"clientPortfolio": {"credit": 0.0, "positions": [
        {"instrumentID": 3000, "units": 1.0, "amount": 100.0, "openRate": 100.0,
         "openDateTime": "2024-01-01T00:00:00.000Z", "isBuy": True, "leverage": 2.0}]}}
    snap = etoro.fetch_etoro_snapshot(FixtureClient(portfolio=portfolio), fx=_FX, as_of="2026-07-13")
    assert snap.positions[0].leverage == 2.0


# -- shape guards ------------------------------------------------------------
def test_snapshot_rejects_non_dict_portfolio():
    class C:
        def get_portfolio(self):
            return ["not a dict"]
        def get_instruments(self, ids):
            return []
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.fetch_etoro_snapshot(C(), fx=_FX, as_of="2026-07-13")
    assert "portfolio object" in str(exc.value)


def test_snapshot_rejects_missing_client_portfolio():
    class C:
        def get_portfolio(self):
            return {"somethingElse": {}}
        def get_instruments(self, ids):
            return []
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.fetch_etoro_snapshot(C(), fx=_FX, as_of="2026-07-13")
    assert "clientPortfolio" in str(exc.value)


def test_snapshot_rejects_non_list_positions():
    portfolio = {"clientPortfolio": {"positions": {"bad": 1}, "credit": 0.0}}
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.fetch_etoro_snapshot(FixtureClient(portfolio=portfolio), fx=_FX, as_of="2026-07-13")
    assert "list of positions" in str(exc.value)


def test_snapshot_rejects_non_dict_position_element():
    portfolio = {"clientPortfolio": {"positions": ["nope"], "credit": 0.0}}
    with pytest.raises(etoro.EtoroError):
        etoro.fetch_etoro_snapshot(FixtureClient(portfolio=portfolio), fx=_FX, as_of="2026-07-13")


def test_snapshot_rejects_position_missing_instrument_id():
    portfolio = {"clientPortfolio": {"credit": 0.0, "positions": [
        {"units": 1.0, "amount": 100.0, "openDateTime": "2024-01-01T00:00:00.000Z"}]}}
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.fetch_etoro_snapshot(FixtureClient(portfolio=portfolio), fx=_FX, as_of="2026-07-13")
    assert "instrumentID" in str(exc.value)


def test_snapshot_raises_when_metadata_missing_for_an_instrument():
    # portfolio references instrumentID 9999 but metadata resolves nothing for it
    portfolio = {"clientPortfolio": {"credit": 0.0, "positions": [
        {"instrumentID": 9999, "units": 1.0, "amount": 100.0, "openRate": 100.0,
         "openDateTime": "2024-01-01T00:00:00.000Z", "isBuy": True, "leverage": 1.0}]}}
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.fetch_etoro_snapshot(FixtureClient(portfolio=portfolio), fx=_FX, as_of="2026-07-13")
    assert "metadata unavailable" in str(exc.value)


def test_snapshot_raises_when_instrument_has_no_symbol():
    portfolio = {"clientPortfolio": {"credit": 0.0, "positions": [
        {"instrumentID": 3000, "units": 1.0, "amount": 100.0, "openRate": 100.0,
         "openDateTime": "2024-01-01T00:00:00.000Z", "isBuy": True, "leverage": 1.0}]}}
    instruments = {"instrumentDisplayDatas": [
        {"instrumentID": 3000, "symbolFull": "", "instrumentTypeID": 6}]}
    with pytest.raises(etoro.EtoroError) as exc:
        etoro.fetch_etoro_snapshot(
            FixtureClient(portfolio=portfolio, instruments=instruments), fx=_FX, as_of="2026-07-13")
    assert "symbolFull" in str(exc.value)


# -- end-to-end: the fixture snapshot ingests via mirror.ingest_snapshot -----
def test_snapshot_ingests_via_mirror(tmp_db):
    from agentcy import db, mirror
    from agentcy.clock import SystemClock
    snap = etoro.fetch_etoro_snapshot(FixtureClient(), fx=_FX, as_of="2026-07-13")
    snapshot_id, deltas = mirror.ingest_snapshot(tmp_db, snap, clock=SystemClock())
    row = db.fetch_latest_snapshot(tmp_db)
    assert row["source"] == "api_pull"
    # two positions land (SPY collapsed from 3 lots, SHOP from 1)
    assert {p["symbol"] for p in db.fetch_positions_records(tmp_db, snapshot_id)} == {"SPY", "SHOP"}
    details = db.fetch_position_details(tmp_db, snapshot_id)
    by_symbol = {d["symbol"]: d for d in details}
    assert by_symbol["SPY"]["lot_count"] == 3
    assert by_symbol["SHOP"]["lot_count"] == 1
    # baseline snapshot: no leverage violations in the sanitized fixture
    assert [d.kind for d in deltas] == []
