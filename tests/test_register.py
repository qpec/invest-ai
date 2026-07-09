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


def _mk(tmp_db, fixed_clock, **kw):
    from agentcy import register
    return register.create_thesis(tmp_db, ticker=kw.pop("ticker", "VEEV"), origin="gate",
                                  fields=_fields(**kw), triggers=_triggers(), journal_ref=1,
                                  clock=fixed_clock)


def test_activate_draft_to_intact(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="position appeared in snapshot", clock=fixed_clock)
    assert db.fetch_current_thesis_status(tmp_db, tid)["status"] == "intact"


def test_under_review_sets_deadline(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    register.transition(tmp_db, tid, "under_review", cause="T2 fired", cause_ref="A1",
                        clock=fixed_clock)
    st = db.fetch_current_thesis_status(tmp_db, tid)
    assert st["status"] == "under_review"
    assert st["review_deadline"] == "2026-07-15T05:00:00Z"      # +7d alert_decision_days


def test_broken_is_terminal(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    register.transition(tmp_db, tid, "under_review", cause="c", cause_ref=None, clock=fixed_clock)
    register.transition(tmp_db, tid, "broken", cause="confirmed", cause_ref=None, clock=fixed_clock)
    with pytest.raises(ValueError, match="broken.*intact|terminal"):
        register.transition(tmp_db, tid, "intact", cause="x", cause_ref=None, clock=fixed_clock)


def test_illegal_draft_to_broken(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    with pytest.raises(ValueError):
        register.transition(tmp_db, tid, "broken", cause="x", cause_ref=None, clock=fixed_clock)


def test_retired_is_terminal(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    register.transition(tmp_db, tid, "retired", cause="closed", cause_ref=None, clock=fixed_clock)
    with pytest.raises(ValueError):
        register.transition(tmp_db, tid, "intact", cause="x", cause_ref=None, clock=fixed_clock)


from datetime import datetime, timezone

from agentcy.clock import FixedClock


def test_revise_bumps_version_with_diff(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    v = register.revise(tmp_db, tid, {"moat_evidence": "retention now >120%"},
                        reason="fresher data", actor="owner", journal_ref=1, clock=fixed_clock)
    assert v == 2
    row = db.fetch_current_thesis_version(tmp_db, tid)
    assert row["version"] == 2 and row["moat_evidence"] == "retention now >120%"
    assert json.loads(row["diff_json"])["moat_evidence"] == ["retention >115%", "retention now >120%"]


def test_band_reanchor_needs_context_and_intact(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    with pytest.raises(ValueError, match="anniversary|event|re-anchor"):
        register.revise(tmp_db, tid, {"fair_band_high": 40.0}, reason="feels cheap",
                        actor="owner", journal_ref=1, clock=fixed_clock)
    v = register.revise(tmp_db, tid, {"fair_band_high": 40.0}, reason="anniversary review",
                        actor="owner", journal_ref=1, clock=fixed_clock, context="anniversary")
    assert v == 2 and db.fetch_current_thesis_version(tmp_db, tid)["fair_band_high"] == 40.0


def test_no_revise_while_under_review(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    register.transition(tmp_db, tid, "under_review", cause="fired", cause_ref=None, clock=fixed_clock)
    with pytest.raises(ValueError, match="under_review|goalpost"):
        register.revise(tmp_db, tid, {"moat_evidence": "x"}, reason="r", actor="owner",
                        journal_ref=1, clock=fixed_clock)


def test_distrust_revision_auto_opens_review(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    register.revise(tmp_db, tid, {"mgmt_trust": "distrust"}, reason="CEO scandal", actor="owner",
                    journal_ref=1, clock=fixed_clock)
    assert db.fetch_current_thesis_status(tmp_db, tid)["status"] == "under_review"


def test_revise_trigger_loosening_only_intact_and_captures_headroom(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    old = db.fetch_armed_triggers(tmp_db, tid)[0]                  # growth_floor threshold 10
    loose = register.TriggerSpec(type="growth_floor", statement="rev YoY < 8% (2q)",
                                 metric="revenue_yoy", comparator="<", threshold=8.0,
                                 moat_link=None, persistence="2_consecutive_quarters")
    new_id = register.revise_trigger(tmp_db, old["trigger_id"], loose, reason="noise",
                                     actor="owner", journal_ref=1, clock=fixed_clock, headroom=2.7)
    armed_ids = {t["trigger_id"] for t in db.fetch_armed_triggers(tmp_db, tid)}
    assert old["trigger_id"] not in armed_ids and new_id in armed_ids   # retire + new row
    echoes = register.loosening_echoes(tmp_db, as_of=fixed_clock.now())
    assert any(e["headroom"] == 2.7 for e in echoes)


def test_revise_trigger_forbidden_under_review(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    register.transition(tmp_db, tid, "under_review", cause="c", cause_ref=None, clock=fixed_clock)
    old = db.fetch_armed_triggers(tmp_db, tid)[0]
    loose = register.TriggerSpec(type="growth_floor", statement="s", metric="revenue_yoy",
                                 comparator="<", threshold=5.0, moat_link=None,
                                 persistence="2_consecutive_quarters")
    with pytest.raises(ValueError, match="intact|goalpost"):
        register.revise_trigger(tmp_db, old["trigger_id"], loose, reason="r", actor="owner",
                                journal_ref=1, clock=fixed_clock, headroom=1.0)


def test_anniversaries_due(tmp_db, fixed_clock):
    from agentcy import register
    tid = _mk(tmp_db, fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)   # activated 2026-07-08
    assert register.anniversaries_due(tmp_db, as_of=fixed_clock.now()) == []
    one_year = datetime(2027, 7, 9, tzinfo=timezone.utc)
    assert register.anniversaries_due(tmp_db, as_of=one_year) == [tid]


def test_guard_repitch_returns_prior_pass(tmp_db, fixed_clock):
    from agentcy import journal, register
    eid = journal.append(tmp_db, journal.EntryIn(decision_type="gate_verdict",
                         decision_subtype="pass", ticker="NVDA",
                         system_recommendation="PASS: outside_circle", actor="system"),
                         clock=fixed_clock)
    got = register.guard_repitch(tmp_db, "NVDA")
    assert got is not None and got["entry_id"] == eid
    assert register.guard_repitch(tmp_db, "VEEV") is None
