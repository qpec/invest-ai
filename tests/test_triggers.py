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


def test_evaluate_armed_appends_checks(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import register, triggers
    from agentcy.fetch import store
    trig, tid = _thesis_with_trigger(tmp_db, fixed_clock, {})
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: stamped([("2026-03-31", 12.1), ("2026-06-30", 14.2)]),
                        raising=False)
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: stamped([("2026-06-30", 25.0)]), raising=False)
    run_id = _mkrun(tmp_db, fixed_clock)
    outs = triggers.evaluate_armed(tmp_db, cadence="weekly", thesis_id=tid, as_of=AS_OF,
                                   run_id=run_id)
    assert {o.result for o in outs} == {"PASS"}
    cur = triggers.current_state(tmp_db, trig["trigger_id"])
    assert cur.result == "PASS" and cur.observed_value == 14.2


def test_fire_moves_thesis_and_mints_alert_and_ask(tmp_db, fixed_clock):
    from agentcy import register, triggers
    trig, tid = _thesis_with_trigger(tmp_db, fixed_clock, {})
    run_id = _mkrun(tmp_db, fixed_clock)
    out = triggers.CheckOutcome(trigger_id=trig["trigger_id"], result="FIRE",
                                observed_value=8.4, headroom=-1.6, evaluable_from=None, note=None)
    alert_id = triggers.fire(tmp_db, out, clock=fixed_clock, run_id=run_id)
    assert db.fetch_current_thesis_status(tmp_db, tid)["status"] == "under_review"
    al = db.fetch_alert(tmp_db, alert_id)
    assert al["deadline"] == "2026-07-15T05:00:00Z" and al["status"] == "open"
    a_asks = db.fetch_asks_for(tmp_db, kind="A", trigger_ref=trig["trigger_id"])
    assert len(a_asks) == 1 and a_asks[0]["alert_ref"] == alert_id


def test_fire_idempotent_while_alert_open(tmp_db, fixed_clock):
    from agentcy import triggers
    trig, tid = _thesis_with_trigger(tmp_db, fixed_clock, {})
    run_id = _mkrun(tmp_db, fixed_clock)
    out = triggers.CheckOutcome(trig["trigger_id"], "FIRE", 8.4, -1.6, None, None)
    a1 = triggers.fire(tmp_db, out, clock=fixed_clock, run_id=run_id)
    a2 = triggers.fire(tmp_db, out, clock=fixed_clock, run_id=run_id)
    assert a1 == a2                                        # no second alert while the first is open
    assert len(db.fetch_asks_for(tmp_db, kind="A", trigger_ref=trig["trigger_id"])) == 1


def test_fire_with_storm_key_shares_deadline(tmp_db, fixed_clock):
    from agentcy import triggers
    trig, tid = _thesis_with_trigger(tmp_db, fixed_clock, {})
    run_id = _mkrun(tmp_db, fixed_clock)
    out = triggers.CheckOutcome(trig["trigger_id"], "FIRE", 8.4, -1.6, None, None)
    aid = triggers.fire(tmp_db, out, clock=fixed_clock, run_id=run_id,
                        storm_key="2026-07-08-storm")
    assert db.fetch_alert(tmp_db, aid)["storm_key"] == "2026-07-08-storm"


def _mkrun(conn, clock):
    from agentcy import runlog
    return runlog.start(conn, "weekly", "2026-07-11", clock=clock).run_id


def test_headroom_table_live(tmp_db, fixed_clock, monkeypatch, stamped):
    from agentcy import triggers
    from agentcy.fetch import store
    trig, tid = _thesis_with_trigger(tmp_db, fixed_clock, {})
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: stamped([("2026-03-31", 12.1), ("2026-06-30", 14.2)]),
                        raising=False)
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: stamped([("2026-06-30", 25.0)]), raising=False)
    table = triggers.headroom_table(tmp_db, tid, as_of=AS_OF)
    by_id = {o.trigger_id: o for o in table}
    assert by_id[trig["trigger_id"]].result == "PASS"
    assert round(by_id[trig["trigger_id"]].headroom, 1) == 4.2


def test_unverifiable_weeks_counts_consecutive(tmp_db, fixed_clock):
    from agentcy import register, triggers
    from datetime import datetime, timezone, timedelta
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
    from agentcy import runlog
    base = datetime(2026, 6, 20, tzinfo=timezone.utc)
    for i in range(3):
        rid = runlog.start(tmp_db, "weekly", f"2026-06-{20 + i * 7}", clock=fixed_clock).run_id
        db.append_trigger_check(tmp_db, {"trigger_id": trig["trigger_id"], "run_id": rid,
            "checked_at": db.to_iso(base + timedelta(days=7 * i)), "result": "UNVERIFIABLE",
            "observed_value": None, "headroom": None, "evaluable_from": None})
    at = datetime(2026, 7, 5, tzinfo=timezone.utc)
    assert triggers.unverifiable_weeks(tmp_db, trig["trigger_id"], as_of=at) == 3


def test_unverifiable_weeks_resets_on_pass(tmp_db, fixed_clock):
    from agentcy import register, runlog, triggers
    from datetime import datetime, timezone, timedelta
    trig, tid = _thesis_with_trigger(tmp_db, fixed_clock, {})
    base = datetime(2026, 6, 20, tzinfo=timezone.utc)
    for i, res in enumerate(["UNVERIFIABLE", "PASS", "UNVERIFIABLE"]):
        rid = runlog.start(tmp_db, "weekly", f"2026-06-{20 + i}", clock=fixed_clock).run_id
        db.append_trigger_check(tmp_db, {"trigger_id": trig["trigger_id"], "run_id": rid,
            "checked_at": db.to_iso(base + timedelta(days=7 * i)), "result": res,
            "observed_value": None, "headroom": None, "evaluable_from": None})
    at = datetime(2026, 7, 10, tzinfo=timezone.utc)
    assert triggers.unverifiable_weeks(tmp_db, trig["trigger_id"], as_of=at) == 1  # only the last
