"""Stage-1 veto/penalty layer (design §2): leverage veto, cash-destruction veto,
dilution penalty, data-integrity suspend. Vetoes SUPPRESS (cap, never rank).

RF2 — the veto consumes the REAL raw ebitda & net_debt (from durability_metrics),
never fabricated placeholders; both the ratio branch and the EBITDA<=0-with-net-debt
branch are exercised here.
RF3 — the cash-destruction veto is PER-PERIOD: ``owner_fcf_positive_any`` is fed the
per-period flag (True only if owner-FCF is positive in some period), NOT the TTM-sum
sign; the veto fires when owner-FCF is negative in every available period.
RF6 — a rising-share case (shares_yoy_pct > 5) proves the -15 dilution penalty fires.
"""
from agentcy import scout_grade as sg


def test_leverage_veto_high_net_debt():
    v = sg.veto_check(net_debt_to_ebitda=6.8, ebitda=1.0, net_debt=6.8,
                      owner_fcf_positive_any=True, shares_yoy_pct=5.0)
    assert v.vetoed and "leverage" in v.reason.lower() and v.penalty == 0


def test_leverage_veto_negative_ebitda_with_debt():
    # RF2 — the EBITDA<=0-with-net-debt branch fires off the REAL raw ebitda/net_debt,
    # not the (uncomputable, None) ratio.
    v = sg.veto_check(net_debt_to_ebitda=None, ebitda=-1.0, net_debt=500.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=0.0)
    assert v.vetoed and "leverage" in v.reason.lower()


def test_negative_ebitda_no_net_debt_not_leverage_vetoed():
    # RF2 — EBITDA<=0 alone (no net debt) is NOT a leverage wreck; net debt <= 0 means
    # the balance sheet is net-cash, so the leverage gate must not trip.
    v = sg.veto_check(net_debt_to_ebitda=None, ebitda=-1.0, net_debt=-500.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=0.0)
    assert not v.vetoed


def test_cash_destruction_veto():
    # RF3 — owner_fcf_positive_any=False means owner-FCF was negative in EVERY period.
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=False, shares_yoy_pct=0.0)
    assert v.vetoed and "cash" in v.reason.lower() and v.penalty == 0


def test_leverage_beats_cash_destruction_when_both_trip():
    # Leverage is the first gate; a name that trips both is reported as a leverage wreck.
    v = sg.veto_check(net_debt_to_ebitda=6.8, ebitda=1.0, net_debt=6.8,
                      owner_fcf_positive_any=False, shares_yoy_pct=0.0)
    assert v.vetoed and "leverage" in v.reason.lower()


def test_dilution_penalty_not_veto():
    # RF6 — rising shares (>5%/yr) fire the -15 dilution penalty; it is a penalty, NOT a veto.
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=8.0)
    assert not v.vetoed and v.penalty == -15 and "dilut" in v.reason.lower()
    assert "8.0%" in v.reason


def test_dilution_penalty_boundary_not_fired_at_threshold():
    # Exactly 5% is NOT > 5% -> no penalty (the §2 rule is strictly greater than 5%/yr).
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=5.0)
    assert not v.vetoed and v.penalty == 0 and v.reason == ""


def test_dilution_penalty_none_shares_no_penalty():
    # A suspended dilution leg (shares_yoy_pct None) must not fabricate a penalty.
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=None)
    assert not v.vetoed and v.penalty == 0 and v.reason == ""


def test_clean_name_no_veto_no_penalty():
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=1.0)
    assert not v.vetoed and v.penalty == 0 and v.reason == ""


def test_veto_is_frozen_dataclass():
    v = sg.veto_check(net_debt_to_ebitda=1.0, ebitda=10.0, net_debt=1.0,
                      owner_fcf_positive_any=True, shares_yoy_pct=1.0)
    import dataclasses
    assert dataclasses.is_dataclass(v)
    try:
        v.vetoed = True
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Veto must be a frozen dataclass")
