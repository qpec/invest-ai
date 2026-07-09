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
