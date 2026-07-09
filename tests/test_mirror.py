"""tests/test_mirror.py — E.1-E.5 Portfolio Mirror."""
import pytest

from agentcy import db


CSV = """\
symbol,instrument_type,quantity,avg_open_price,native_currency,market_value_native,market_value_eur,leverage
VEEV,stock,10,200.0,USD,2500.0,2300.0,1.0
CRWD,stock,5,300.0,USD,1600.0,1472.0,1.0
CASH,cash,0,0,EUR,300.0,300.0,1.0
"""


def test_parse_etoro_csv_canonical(fixed_clock):
    from agentcy import mirror
    snap = mirror.parse_etoro_csv(CSV)
    assert snap.cash_balance_eur == 300.0 and snap.source == "manual_export"
    syms = {p.symbol: p for p in snap.positions}
    assert set(syms) == {"VEEV", "CRWD"}                  # cash is not a position
    # weights are fractions of invested MV (2300+1472=3772)
    assert round(syms["VEEV"].weight, 4) == round(2300.0 / 3772.0, 4)
    assert syms["VEEV"].avg_open_price == 200.0 and syms["VEEV"].leverage == 1.0


def test_parse_etoro_csv_malformed_reports_line(fixed_clock):
    from agentcy import mirror
    bad = CSV.replace("5,300.0,USD,1600.0,1472.0,1.0", "notanumber,300.0,USD,1600.0,1472.0,1.0")
    with pytest.raises(ValueError, match="line 2"):     # CRWD is the 2nd DictReader data row
        mirror.parse_etoro_csv(bad)


def test_parse_manual_text(fixed_clock):
    from agentcy import mirror
    txt = "cash: 300\nVEEV 10 2300 USD\nCRWD 5 1472 USD\n"
    snap = mirror.parse_manual_text(txt)
    assert snap.source == "manual_entry" and snap.cash_balance_eur == 300.0
    assert {p.symbol for p in snap.positions} == {"VEEV", "CRWD"}
    assert all(p.avg_open_price is None for p in snap.positions)


def _pos(symbol, qty, mv, lev=1.0, itype="stock", ccy="USD"):
    from agentcy import mirror
    return mirror.PositionIn(symbol=symbol, yf_ticker=symbol, instrument_type=itype, quantity=qty,
                             avg_open_price=None, native_currency=ccy, mv_native=mv, mv_eur=mv,
                             weight=0.0, leverage=lev)


def _snap(cash, positions, source="manual_entry", as_of="2026-07-08"):
    from agentcy import mirror
    return mirror.SnapshotIn(as_of=as_of, source=source, cash_balance_eur=cash,
                             positions=tuple(positions))


def test_first_ingest_no_appeared_deltas(tmp_db, fixed_clock):
    from agentcy import mirror
    sid, deltas = mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("VEEV", 10, 2300)]),
                                         clock=fixed_clock)
    assert sid == 1 and [d.kind for d in deltas] == []       # baseline, nothing to reconcile
    assert db.fetch_latest_snapshot(tmp_db)["cash_balance_eur"] == 300.0


def test_appeared_and_disappeared(tmp_db, fixed_clock):
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("VEEV", 10, 2300)],
                           as_of="2026-07-01"), clock=fixed_clock)
    _, deltas = mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("CRWD", 5, 1500)],
                                       as_of="2026-07-08"), clock=fixed_clock)
    kinds = {(d.kind, d.symbol) for d in deltas}
    assert ("appeared", "CRWD") in kinds and ("disappeared", "VEEV") in kinds


def test_quantity_change(tmp_db, fixed_clock):
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("MSFT", 40, 4000)], as_of="2026-07-01"),
                           clock=fixed_clock)
    _, deltas = mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("MSFT", 55, 5500)],
                                       as_of="2026-07-08"), clock=fixed_clock)
    qd = [d for d in deltas if d.kind == "quantity_change"]
    assert len(qd) == 1 and qd[0].old_value == 40 and qd[0].new_value == 55


def test_unexplained_cash_pure_deposit(tmp_db, fixed_clock):
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("VEEV", 10, 2300)], as_of="2026-07-01"),
                           clock=fixed_clock)
    _, deltas = mirror.ingest_snapshot(tmp_db, _snap(4500.0, [_pos("VEEV", 10, 2300)],
                                       as_of="2026-07-08"), clock=fixed_clock)
    uc = [d for d in deltas if d.kind == "unexplained_cash"]
    assert len(uc) == 1 and uc[0].new_value == 4200.0        # +4200 with no position change


def test_leverage_tripwire(tmp_db, fixed_clock):
    from agentcy import mirror
    _, deltas = mirror.ingest_snapshot(tmp_db, _snap(0.0, [_pos("XLEV", 1, 1000, lev=2.0)]),
                                       clock=fixed_clock)
    lv = [d for d in deltas if d.kind == "leverage_violation"]
    assert len(lv) == 1 and lv[0].symbol == "XLEV"


def test_advice_positions_no_cost_basis(tmp_db, fixed_clock):
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("VEEV", 10, 2300)]), clock=fixed_clock)
    ap = mirror.advice_positions(tmp_db)
    assert [p.symbol for p in ap] == ["VEEV"]
    assert not hasattr(ap[0], "avg_open_price")            # invariant 4: structurally absent


def test_framework_status_defaults_and_designation(tmp_db, fixed_clock):
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(0.0, [
        _pos("VEEV", 10, 2300, itype="stock"),
        _pos("BTC", 1, 5000, itype="crypto"),
        _pos("SPY", 5, 2000, itype="etf")]), clock=fixed_clock)
    at = fixed_clock.now()
    assert mirror.framework_status(tmp_db, "VEEV", as_of=at) == "backfill_pending"
    assert mirror.framework_status(tmp_db, "BTC", as_of=at) == "outside_framework"
    assert mirror.framework_status(tmp_db, "SPY", as_of=at) == "outside_framework"
    mirror.designate(tmp_db, "VEEV", "framework", journal_ref=1, valid_from=db.to_iso(at))
    assert mirror.framework_status(tmp_db, "VEEV", as_of=at) == "framework"


def test_backfill_queue_by_weight_desc(tmp_db, fixed_clock):
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(0.0, [
        _pos("AAA", 1, 1000, itype="stock"),
        _pos("BBB", 1, 3000, itype="stock")]), clock=fixed_clock)
    # both default backfill_pending; BBB heavier -> first
    assert mirror.backfill_queue(tmp_db, as_of=fixed_clock.now()) == ["BBB", "AAA"]


def test_snapshot_age(tmp_db, fixed_clock):
    from datetime import datetime, timezone, timedelta
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(0.0, [_pos("VEEV", 10, 2300)], as_of="2026-07-01"),
                           clock=fixed_clock)
    age = mirror.snapshot_age(tmp_db, as_of=datetime(2026, 7, 8, tzinfo=timezone.utc))
    assert age == timedelta(days=7)
    assert mirror.snapshot_age(tmp_db, as_of=None) is None or isinstance(age, timedelta)


def test_balance_bands_and_unpriced_weight(tmp_db, fixed_clock):
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(1000.0, [                 # cash 1000
        _pos("VEEV", 10, 6000, itype="stock"),                     # 6000
        _pos("CRWD", 5, 3000, itype="stock"),                      # 3000
        _pos("COPY", 1, 1000, itype="copyportfolio")]),            # non-mappable (yf None)
        clock=fixed_clock)
    mirror.designate(tmp_db, "VEEV", "framework", journal_ref=1, valid_from=db.to_iso(fixed_clock.now()))
    mirror.designate(tmp_db, "CRWD", "framework", journal_ref=1, valid_from=db.to_iso(fixed_clock.now()))
    mirror.designate(tmp_db, "COPY", "outside_framework", journal_ref=1,
                     valid_from=db.to_iso(fixed_clock.now()))
    rep = mirror.balance(tmp_db, as_of=fixed_clock.now())
    invested = 6000 + 3000 + 1000
    assert round(rep.cash_pct, 2) == round(100 * 1000 / (1000 + invested), 2)
    assert rep.n_framework == 2 and rep.n_outside == 1 and rep.n_backfill == 0
    # VEEV weight = 6000/10000 = 60% > hard 20%
    assert "VEEV" in rep.hard_cap_breaches and "VEEV" in rep.soft_cap_breaches
    # COPY is non-mappable -> unpriced weight printed
    assert round(rep.unpriced_weight_pct, 1) == round(100 * 1000 / invested, 1)
    # no returns frame passed -> N_eff suspended
    assert rep.n_eff is None and rep.n_eff_ok is None


def test_balance_cash_band_and_outside_cap(tmp_db, fixed_clock):
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(100.0, [
        _pos("VEEV", 10, 4500, itype="stock"),
        _pos("BTC", 1, 500, itype="crypto")]), clock=fixed_clock)
    mirror.designate(tmp_db, "VEEV", "framework", journal_ref=1, valid_from=db.to_iso(fixed_clock.now()))
    mirror.designate(tmp_db, "BTC", "outside_framework", journal_ref=1,
                     valid_from=db.to_iso(fixed_clock.now()))
    rep = mirror.balance(tmp_db, as_of=fixed_clock.now())
    assert rep.cash_in_band is False                       # 100/5100 ≈ 1.96% < 5% band low
    # BTC 500/5000 = 10% outside == cap 10% -> ok (not strictly above)
    assert rep.outside_cap_ok is True


def test_balance_with_returns_computes_n_eff(tmp_db, fixed_clock):
    import numpy as np, pandas as pd
    from agentcy import mirror
    mirror.ingest_snapshot(tmp_db, _snap(0.0, [
        _pos("A", 1, 4000, itype="stock"), _pos("B", 1, 4000, itype="stock"),
        _pos("C", 1, 2000, itype="stock")]), clock=fixed_clock)
    rng = np.random.default_rng(1)
    base = rng.normal(0, 0.01, 200)
    idx = pd.date_range("2025-01-01", periods=200, freq="B")
    rets = pd.DataFrame({"A": base + rng.normal(0, 0.001, 200),
                         "B": base + rng.normal(0, 0.001, 200),
                         "C": rng.normal(0, 0.01, 200)}, index=idx)
    rep = mirror.balance(tmp_db, as_of=fixed_clock.now(), returns_local=rets)
    assert rep.n_eff is not None and rep.n_eff_ok is not None
