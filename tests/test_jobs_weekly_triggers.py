"""P6.10: D.2 check 2 — full re-test of armed automated triggers; fires -> alert path (B.3);
storms bundle with shared storm_key/deadline (B.3.5); weekly prompted questions -> Q asks."""
from datetime import datetime, timezone

from agentcy import db, runlog, triggers
from agentcy.clock import FixedClock
from agentcy.freshness import CheckResult
from agentcy.triggers import CheckOutcome

SAT = FixedClock(datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc))


def _outcome(trigger_id, result=CheckResult.PASS, observed=25.0):
    return CheckOutcome(trigger_id=trigger_id, result=result, observed_value=observed,
                        headroom=5.0, evaluable_from=None, note=None)


def test_fire_creates_alert_ask_and_enqueues_alert_first_key(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    auto = [t for t in db.fetch_armed_triggers(conn, seeded_portfolio["thesis_id"])
            if t["check_method"] == "automated"][0]
    monkeypatch.setattr(triggers, "evaluate_armed",
                        lambda c, *, cadence, thesis_id=None, as_of, run_id:
                        [_outcome(auto["trigger_id"], CheckResult.FIRE, 17.1)])
    rh = runlog.start(conn, "weekly", "2026-07-11", clock=SAT)
    out = weekly.run_trigger_tests(conn, run_id=rh.run_id, clock=SAT)
    assert len(out["fired_alert_ids"]) == 1
    alert_id = out["fired_alert_ids"][0]
    alert = db.fetch_alert(conn, alert_id)
    assert alert["status"] == "open" and alert["storm_key"] is None
    assert db.fetch_current_thesis_status(conn, seeded_portfolio["thesis_id"])["status"] == "under_review"
    ob = db.fetch_outbox_by_key(conn, f"alert:{alert_id}")
    assert ob is not None and ob["kind"] == "alert"
    assert "WHAT THIS IS NOT" in ob["payload_html"]           # G.3 verbatim block survives lint


def test_storm_bundles_with_shared_storm_key_and_one_message(seeded_portfolio, fixed_clock,
                                                             tmp_path, monkeypatch):
    from agentcy import register
    from agentcy.register import TriggerSpec
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    tid = seeded_portfolio["thesis_id"]
    second = register.commit_trigger(conn, tid, TriggerSpec(
        type="dilution", statement="If shares outstanding grow > 3% in 12 months, I am being diluted out.",
        metric="shares_yoy", comparator=">", threshold=3.0, moat_link=None,
        persistence="ttm"), introduced_version=1, journal_ref=seeded_portfolio["journal_ref"])
    autos = [t for t in db.fetch_armed_triggers(conn, tid) if t["check_method"] == "automated"]
    monkeypatch.setattr(triggers, "evaluate_armed",
                        lambda c, *, cadence, thesis_id=None, as_of, run_id:
                        [_outcome(t["trigger_id"], CheckResult.FIRE, 1.0) for t in autos])
    rh = runlog.start(conn, "weekly", "2026-07-11b", clock=SAT)
    out = weekly.run_trigger_tests(conn, run_id=rh.run_id, clock=SAT)
    assert len(out["fired_alert_ids"]) == 2
    a1, a2 = (db.fetch_alert(conn, i) for i in out["fired_alert_ids"])
    assert a1["storm_key"] == a2["storm_key"] is not None     # shared storm key
    assert a1["deadline"] == a2["deadline"]                   # one shared decision window
    bundled = db.fetch_outbox_by_key(conn, f"alert:{min(out['fired_alert_ids'])}")
    assert bundled is not None
    assert db.fetch_outbox_by_key(conn, f"alert:{max(out['fired_alert_ids'])}") is None  # ONE message


def test_weekly_prompted_question_minted_once(seeded_portfolio, monkeypatch):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    tid = seeded_portfolio["thesis_id"]
    # a type-5 trigger flagged weekly (B.2 'weekly if flagged urgent'): insert directly
    trig_id = db.append_trigger(conn, dict(
        thesis_id=tid, introduced_version=1, type="owner_attested_event",
        statement="Is NRR still >= 110%?", metric=None, comparator=None, threshold=None,
        moat_link=None, persistence="single_observation", check_method="prompted",
        data_source="owner_attestation", cadence="weekly", yes_means="pass"))
    rh = runlog.start(conn, "weekly", "2026-07-11q", clock=SAT)
    minted = weekly.queue_prompted_questions(conn, run_id=rh.run_id, clock=SAT)
    assert len(minted) == 1
    ask = db.fetch_ask(conn, minted[0])
    assert ask["kind"] == "Q" and ask["trigger_ref"] == trig_id
    assert weekly.queue_prompted_questions(conn, run_id=rh.run_id, clock=SAT) == []   # already open: no dup
