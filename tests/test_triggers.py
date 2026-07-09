"""tests/test_triggers.py — the five B.2 evaluators."""
from datetime import datetime, timezone

import pytest

from agentcy import db
from agentcy.freshness import DataState


AS_OF = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def _thesis_with_trigger(tmp_db, fixed_clock, spec_kw):
    from agentcy import register
    fields = _rfields()
    t = register.TriggerSpec(**{**dict(type="growth_floor", statement="s", metric="revenue_yoy",
                                       comparator="<", threshold=10.0, moat_link=None,
                                       persistence="2_consecutive_quarters"), **spec_kw})
    moat = register.TriggerSpec(type="margin_erosion", statement="s", metric="owner_fcf_margin",
                                comparator="<", threshold=20.0, moat_link="switching_costs",
                                persistence="ttm")
    tid = register.create_thesis(tmp_db, ticker="VEEV", origin="gate", fields=fields,
                                 triggers=[t, moat], journal_ref=1, clock=fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    return db.fetch_armed_triggers(tmp_db, tid)[0], tid


def _rfields(**kw):
    from agentcy import register
    base = dict(business_model_2s="a. b.", moat_types=("switching_costs",), moat_evidence="e",
                owner_earnings_json="{}", owner_earnings_narrative="n", value_at_purchase=None,
                fair_band_low=25.0, fair_band_high=35.0, denominator_note=None, conviction="high",
                mgmt_trust="neutral", mgmt_trust_note=None, circle_fit="core", circle_fit_note=None,
                ten_year_statement="t", status_buy_flag=False, status_buy_note=None)
    base.update(kw)
    return register.ThesisFields(**base)


def test_growth_floor_pass_with_headroom(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import triggers
    from agentcy.fetch import store
    trig, _ = _thesis_with_trigger(tmp_db, fixed_clock, {})
    # revenue_yoy series [14.2, 12.1]: last two both above floor 10 -> PASS
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: stamped([("2026-03-31", 12.1), ("2026-06-30", 14.2)]),
                        raising=False)
    out = triggers.evaluate(tmp_db, trig, as_of=AS_OF)
    assert out.result == "PASS" and out.observed_value == 14.2 and round(out.headroom, 1) == 4.2


def test_growth_floor_fires_two_consecutive(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import triggers
    from agentcy.fetch import store
    trig, _ = _thesis_with_trigger(tmp_db, fixed_clock, {})
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: stamped([("2026-03-31", 9.1), ("2026-06-30", 8.4)]),
                        raising=False)
    out = triggers.evaluate(tmp_db, trig, as_of=AS_OF)
    assert out.result == "FIRE" and round(out.headroom, 1) == -1.6


def test_growth_floor_no_fire_single_breach(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import triggers
    from agentcy.fetch import store
    trig, _ = _thesis_with_trigger(tmp_db, fixed_clock, {})
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: stamped([("2026-03-31", 12.0), ("2026-06-30", 8.4)]),
                        raising=False)
    assert triggers.evaluate(tmp_db, trig, as_of=AS_OF).result == "PASS"   # only one quarter breached


def test_stale_input_never_fires(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import triggers
    from agentcy.fetch import store
    trig, _ = _thesis_with_trigger(tmp_db, fixed_clock, {})
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: stamped([("2026-06-30", 5.0)], state="stale"),
                        raising=False)
    assert triggers.evaluate(tmp_db, trig, as_of=AS_OF).result == "STALE"


def test_bootstrapping_when_archive_too_short(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import triggers
    from agentcy.fetch import store
    trig, _ = _thesis_with_trigger(tmp_db, fixed_clock, {})   # needs 2 quarters
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: stamped([("2026-06-30", 8.0)]),   # only 1 quarter
                        raising=False)
    out = triggers.evaluate(tmp_db, trig, as_of=AS_OF)
    assert out.result == "BOOTSTRAPPING" and out.evaluable_from == "2026-09-29"   # +91d


def test_dilution_fires(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import register, triggers
    from agentcy.fetch import store
    tid = register.create_thesis(tmp_db, ticker="NET", origin="gate", fields=_rfields(),
        triggers=[register.TriggerSpec(type="dilution", statement="shares +3%/12m",
                    metric="shares_yoy", comparator=">", threshold=3.0, moat_link="brand_trust",
                    persistence="single_observation"),
                  register.TriggerSpec(type="growth_floor", statement="s", metric="revenue_yoy",
                    comparator="<", threshold=10.0, moat_link=None,
                    persistence="single_observation")],
        journal_ref=1, clock=fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    trig = [t for t in db.fetch_armed_triggers(tmp_db, tid) if t["type"] == "dilution"][0]
    monkeypatch.setattr(store, "shares_yoy", lambda c, t, *, as_of: stamped(3.6), raising=False)
    out = triggers.evaluate(tmp_db, trig, as_of=AS_OF)
    assert out.result == "FIRE" and out.observed_value == 3.6 and round(out.headroom, 1) == -0.6


def test_margin_erosion_ttm_fires(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import triggers
    from agentcy.fetch import store
    trig, tid = _thesis_with_trigger(tmp_db, fixed_clock, {})
    margin_trig = [t for t in db.fetch_armed_triggers(tmp_db, tid)
                   if t["type"] == "margin_erosion"][0]                 # threshold 20, ttm
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: stamped([("2026-06-30", 17.1)]), raising=False)
    out = triggers.evaluate(tmp_db, margin_trig, as_of=AS_OF)
    assert out.result == "FIRE" and out.observed_value == 17.1


def test_balance_safety_stale_when_row_missing(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import register, triggers
    from agentcy.fetch import store
    tid = register.create_thesis(tmp_db, ticker="ABC", origin="gate", fields=_rfields(),
        triggers=[register.TriggerSpec(type="balance_sheet_safety", statement="netdebt/ebitda>3",
                    metric="net_debt_ebitda", comparator=">", threshold=3.0,
                    moat_link="cost_advantage", persistence="single_observation"),
                  register.TriggerSpec(type="growth_floor", statement="s", metric="revenue_yoy",
                    comparator="<", threshold=10.0, moat_link=None,
                    persistence="single_observation")],
        journal_ref=1, clock=fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    trig = [t for t in db.fetch_armed_triggers(tmp_db, tid)
            if t["type"] == "balance_sheet_safety"][0]
    monkeypatch.setattr(store, "balance_safety_series",
                        lambda c, t, *, as_of: stamped([], state="stale"), raising=False)
    assert triggers.evaluate(tmp_db, trig, as_of=AS_OF).result == "STALE"


def test_prompted_unverifiable_without_answer(tmp_db, fixed_clock):
    from agentcy import register, triggers
    tid = register.create_thesis(tmp_db, ticker="VEEV", origin="gate", fields=_rfields(),
        triggers=[register.TriggerSpec(type="owner_attested_event",
                    statement="Has the founder departed?", metric=None, comparator=None,
                    threshold=None, moat_link="switching_costs", persistence="single_observation",
                    yes_means="fire"),
                  register.TriggerSpec(type="growth_floor", statement="s", metric="revenue_yoy",
                    comparator="<", threshold=10.0, moat_link=None,
                    persistence="single_observation")],
        journal_ref=1, clock=fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    trig = [t for t in db.fetch_armed_triggers(tmp_db, tid)
            if t["type"] == "owner_attested_event"][0]
    assert triggers.evaluate(tmp_db, trig, as_of=AS_OF).result == "UNVERIFIABLE"


def test_prompted_yes_fires_when_yes_means_fire(tmp_db, fixed_clock):
    from agentcy import asks, register, triggers
    tid = register.create_thesis(tmp_db, ticker="VEEV", origin="gate", fields=_rfields(),
        triggers=[register.TriggerSpec(type="owner_attested_event", statement="departed?",
                    metric=None, comparator=None, threshold=None, moat_link="switching_costs",
                    persistence="single_observation", yes_means="fire"),
                  register.TriggerSpec(type="growth_floor", statement="s", metric="revenue_yoy",
                    comparator="<", threshold=10.0, moat_link=None,
                    persistence="single_observation")],
        journal_ref=1, clock=fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    trig = [t for t in db.fetch_armed_triggers(tmp_db, tid)
            if t["type"] == "owner_attested_event"][0]
    q = asks.mint(tmp_db, kind="Q", prompt="departed?", options=["yes", "no", "cant"],
                  expects_freetext=True, thesis_ref=tid, trigger_ref=trig["trigger_id"],
                  clock=fixed_clock)
    asks.answer(tmp_db, q.ask_id, choice="yes", clock=fixed_clock)
    assert triggers.evaluate(tmp_db, trig, as_of=AS_OF).result == "FIRE"
