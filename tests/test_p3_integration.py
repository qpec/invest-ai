"""tests/test_p3_integration.py — the domain modules compose (B.3 loop, resolution, re-export)."""
from datetime import datetime, timezone

import pytest

from agentcy import asks, db, register, runlog, triggers
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def _armed_thesis(conn, clock):
    fields = register.ThesisFields(
        business_model_2s="A. B.", moat_types=("switching_costs",), moat_evidence="e",
        owner_earnings_json="{}", owner_earnings_narrative="n", value_at_purchase=None,
        fair_band_low=25.0, fair_band_high=35.0, denominator_note=None, conviction="high",
        mgmt_trust="trusted_owner_operator", mgmt_trust_note=None, circle_fit="core",
        circle_fit_note=None, ten_year_statement="t", status_buy_flag=False, status_buy_note=None)
    ts = [register.TriggerSpec(type="growth_floor", statement="rev YoY < 10% (2q)",
            metric="revenue_yoy", comparator="<", threshold=10.0, moat_link=None,
            persistence="2_consecutive_quarters"),
          register.TriggerSpec(type="margin_erosion", statement="owner-FCF margin < 20%",
            metric="owner_fcf_margin", comparator="<", threshold=20.0, moat_link="switching_costs",
            persistence="ttm")]
    tid = register.create_thesis(conn, ticker="CRWD", origin="gate", fields=fields, triggers=ts,
                                 journal_ref=1, clock=clock)
    register.activate(conn, tid, cause="position appeared", clock=clock)
    return tid


def test_fire_alert_ask_answer_resolve(tmp_db, fixed_clock, monkeypatch, stamped):
    tid = _armed_thesis(tmp_db, fixed_clock)
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: stamped([("2026-03-31", 9.1), ("2026-06-30", 8.4)]),
                        raising=False)
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: stamped([("2026-06-30", 25.0)]), raising=False)
    run_id = runlog.start(tmp_db, "weekly", "2026-07-11", clock=fixed_clock).run_id

    # 1) evaluate armed -> growth_floor FIREs, margin PASSes
    outs = triggers.evaluate_armed(tmp_db, cadence="weekly", thesis_id=tid, as_of=AS_OF,
                                   run_id=run_id)
    fired = [o for o in outs if o.result == "FIRE"]
    assert len(fired) == 1

    # 2) fire -> under_review + alert + A-ask
    alert_id = triggers.fire(tmp_db, fired[0], clock=fixed_clock, run_id=run_id)
    assert db.fetch_current_thesis_status(tmp_db, tid)["status"] == "under_review"
    [a_ask] = db.fetch_asks_for(tmp_db, kind="A", trigger_ref=fired[0].trigger_id)

    # 3) owner refutes -> drive the PRODUCTION resolution entry point only (asks.answer accepts
    #    the decision, asks.apply_consequence is the shared B.3 dispatcher BOTH the daemon and
    #    the CLI delegate to). No hand-stitched journal/register/alert calls here: the dispatcher
    #    itself must journal trigger_resolution[refuted], return the thesis to intact, and resolve
    #    the alert. If that wiring regresses, THIS test fails.
    out = asks.answer(tmp_db, a_ask["ask_id"], choice="refute", text="one-off billing timing",
                      clock=fixed_clock)
    assert out.consequence == "alert.refute"
    asks.apply_consequence(tmp_db, out, clock=fixed_clock,
                           evidence="billing timing; moat intact", run_id=run_id)

    # thesis back to intact, alert resolved as refuted, no open alerts — all from the dispatcher:
    assert db.fetch_current_thesis_status(tmp_db, tid)["status"] == "intact"
    resolved = db.fetch_alert(tmp_db, alert_id)
    assert resolved["status"] == "refuted"
    assert db.fetch_open_alerts(tmp_db) == []

    # global invariant 2: the owner decision produced a JournalEntry (written by the dispatcher,
    # carrying the verbatim evidence), and it is the alert's resolution reference.
    je = db.fetch_journal_entry(tmp_db, resolved["resolution_journal_ref"])
    assert je["decision_type"] == "trigger_resolution" and je["decision_subtype"] == "refuted"
    assert je["ask_ref"] == a_ask["ask_id"]
    assert "billing timing; moat intact" in je["reasoning_at_the_moment"]


def test_studycontext_reexport_is_performance_free():
    from agentcy.study import StudyContext
    fields = set(StudyContext.__dataclass_fields__)
    assert fields == {"restudy_ticker", "restudy_excerpt", "restudy_question",
                      "mental_model_prompt", "journal_previews", "reading_line",
                      "circle_note_ask_id"}
    assert not any("perf" in f or "return" in f or "pnl" in f for f in fields)
