"""tests/test_register.py — A.1/A.2/A.3 Thesis Register."""
import json

import pytest

from agentcy import db


def _fields(**kw):
    from agentcy import register
    base = dict(
        business_model_2s="Veeva sells regulated life-sciences SaaS. Customers cannot leave.",
        moat_types=("switching_costs", "regulatory_barrier"), moat_evidence="retention >115%",
        owner_earnings_json="{}", owner_earnings_narrative="cash up front",
        value_at_purchase=None, fair_band_low=25.0, fair_band_high=35.0, denominator_note=None,
        conviction="high", mgmt_trust="trusted_owner_operator", mgmt_trust_note=None,
        circle_fit="core", circle_fit_note=None,
        ten_year_statement="Yes; regulation only accumulates.",
        status_buy_flag=False, status_buy_note=None)
    base.update(kw)
    return register.ThesisFields(**base)


def _triggers():
    from agentcy import register
    return [
        register.TriggerSpec(type="growth_floor", statement="rev YoY < 10% (2q)",
                             metric="revenue_yoy", comparator="<", threshold=10.0, moat_link=None,
                             persistence="2_consecutive_quarters"),
        register.TriggerSpec(type="margin_erosion", statement="owner-FCF margin < 20%",
                             metric="owner_fcf_margin", comparator="<", threshold=20.0,
                             moat_link="switching_costs", persistence="2_consecutive_quarters"),
    ]


def test_create_thesis_mints_id_v1_draft(tmp_db, fixed_clock):
    from agentcy import register
    tid = register.create_thesis(tmp_db, ticker="VEEV", origin="gate", fields=_fields(),
                                 triggers=_triggers(), journal_ref=1, clock=fixed_clock)
    assert tid == "TH-VEEV-001"
    assert db.fetch_current_thesis_version(tmp_db, tid)["version"] == 1
    assert db.fetch_current_thesis_status(tmp_db, tid)["status"] == "draft"
    assert len(db.fetch_armed_triggers(tmp_db, tid)) == 2


def test_second_thesis_same_ticker_increments(tmp_db, fixed_clock):
    from agentcy import register
    register.create_thesis(tmp_db, ticker="VEEV", origin="gate", fields=_fields(),
                           triggers=_triggers(), journal_ref=1, clock=fixed_clock)
    tid2 = register.create_thesis(tmp_db, ticker="VEEV", origin="gate", fields=_fields(),
                                  triggers=_triggers(), journal_ref=1, clock=fixed_clock)
    assert tid2 == "TH-VEEV-002"


def test_reject_three_sentences(tmp_db, fixed_clock):
    from agentcy import register
    f = _fields(business_model_2s="One. Two. Three.")
    with pytest.raises(ValueError, match="2 sentence"):
        register.create_thesis(tmp_db, ticker="X", origin="gate", fields=f,
                               triggers=_triggers(), journal_ref=1, clock=fixed_clock)


def test_reject_no_moat_type(tmp_db, fixed_clock):
    from agentcy import register
    with pytest.raises(ValueError, match="moat"):
        register.create_thesis(tmp_db, ticker="X", origin="gate", fields=_fields(moat_types=()),
                               triggers=_triggers(), journal_ref=1, clock=fixed_clock)


def test_reject_too_few_triggers(tmp_db, fixed_clock):
    from agentcy import register
    with pytest.raises(ValueError, match="2.*5|between 2"):
        register.create_thesis(tmp_db, ticker="X", origin="gate", fields=_fields(),
                               triggers=_triggers()[:1], journal_ref=1, clock=fixed_clock)


def test_reject_no_moat_linked_trigger(tmp_db, fixed_clock):
    from agentcy import register
    ts = _triggers()
    ts[1] = register.TriggerSpec(type="margin_erosion", statement="s", metric="m", comparator="<",
                                 threshold=20.0, moat_link=None, persistence="ttm")
    with pytest.raises(ValueError, match="moat_link"):
        register.create_thesis(tmp_db, ticker="X", origin="gate", fields=_fields(),
                               triggers=ts, journal_ref=1, clock=fixed_clock)


def test_reject_bad_horizon(tmp_db, fixed_clock):
    from agentcy import register
    # ThesisFields has no time_horizon field; create_thesis pins it — but conviction enum is checked
    with pytest.raises(ValueError, match="conviction"):
        register.create_thesis(tmp_db, ticker="X", origin="gate",
                               fields=_fields(conviction="insane"),
                               triggers=_triggers(), journal_ref=1, clock=fixed_clock)
