"""P6.18: event job drains the spool per §1.5; one RunLog per request; quiet vs fired outcome."""
import json
from datetime import datetime, timezone

from agentcy import db, events, triggers
from agentcy.clock import FixedClock
from agentcy.events import EventRequest
from agentcy.freshness import CheckResult
from agentcy.triggers import CheckOutcome

EVT = FixedClock(datetime(2026, 7, 24, 6, 0, tzinfo=timezone.utc))


def _spool(state_dir, ticker="MSFT", detected_at="2026-07-24T05:00:00Z", source="fingerprint"):
    events.spool_write(state_dir, EventRequest(yf_ticker=ticker, source=source, kind="earnings",
                                               note="Q earnings", detected_at=detected_at))


def _stub_fresh(monkeypatch, outcome_result=CheckResult.PASS):
    from agentcy.jobs import event as event_mod
    monkeypatch.setattr(event_mod, "fetch_fresh_statements",
                        lambda conn, yf_ticker, *, run_id, clock, state_dir: ["fp-fresh"])
    monkeypatch.setattr(triggers, "evaluate_armed",
                        lambda c, *, cadence, thesis_id=None, as_of, run_id:
                        [CheckOutcome(trigger_id=1, result=outcome_result, observed_value=25.0,
                                      headroom=5.0, evaluable_from=None, note=None)])


def test_drain_quiet_outcome_archives_report_and_no_alert(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import event as event_mod
    conn = seeded_portfolio["conn"]
    _spool(tmp_path)
    _stub_fresh(monkeypatch, CheckResult.PASS)
    rc = event_mod.main(clock=EVT, state_dir=tmp_path)
    assert rc == 0
    assert events.spool_paths(tmp_path) == []                 # drained
    assert (tmp_path / "spool" / "done").exists()             # moved out of the watched dir first
    run = db.fetch_run(conn, "event", "MSFT:2026-07-24T05:00:00Z")
    assert run is not None and run["status"] == "ok"
    assert len(db.fetch_reports(conn, type="event")) == 1     # quiet -> event report archived
    assert db.fetch_open_alerts(conn) == []                   # no alert on a quiet outcome
    # the quiet outputs must carry the keys daily.events_line() consumes to fold the line in (P6.7):
    out = json.loads(run["outputs_json"])
    assert out.get("quiet") is True and out.get("triggers_pass") == "1/1"


def test_drain_fire_takes_alert_path_not_event_report(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import event as event_mod
    conn = seeded_portfolio["conn"]
    auto = [t for t in db.fetch_armed_triggers(conn, seeded_portfolio["thesis_id"])
            if t["check_method"] == "automated"][0]
    _spool(tmp_path)
    monkeypatch.setattr(event_mod, "fetch_fresh_statements",
                        lambda conn, yf_ticker, *, run_id, clock, state_dir: ["fp-fresh"])
    monkeypatch.setattr(triggers, "evaluate_armed",
                        lambda c, *, cadence, thesis_id=None, as_of, run_id:
                        [CheckOutcome(trigger_id=auto["trigger_id"], result=CheckResult.FIRE,
                                      observed_value=17.1, headroom=None, evaluable_from=None, note=None)])
    event_mod.main(clock=EVT, state_dir=tmp_path)
    alerts = db.fetch_open_alerts(conn)
    assert len(alerts) == 1                                    # fire -> alert path (B.3.1)
    assert db.fetch_outbox_by_key(conn, f"alert:{alerts[0]['alert_id']}") is not None


def test_poison_spool_file_goes_to_failed_not_a_loop(tmp_db, tmp_path, monkeypatch):
    from agentcy.jobs import event as event_mod
    (tmp_path / "spool" / "events").mkdir(parents=True)
    (tmp_path / "spool" / "events" / "garbage.json").write_text("{ not json", encoding="utf-8")
    rc = event_mod.main(clock=EVT, state_dir=tmp_path)
    assert rc == 0
    assert events.spool_paths(tmp_path) == []                 # watched dir emptied
    assert (tmp_path / "spool" / "failed" / "garbage.json").exists()


def test_owner_initiated_event_sends_ack_line(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import event as event_mod
    conn = seeded_portfolio["conn"]
    _spool(tmp_path, source="owner")
    _stub_fresh(monkeypatch, CheckResult.PASS)
    event_mod.main(clock=EVT, state_dir=tmp_path)
    # quiet owner-initiated event enqueues an immediate calm acknowledgement (tg-spec §2.4):
    key = "event:MSFT:2026-07-24T05:00:00Z:report"
    ob = db.fetch_outbox_by_key(conn, key)
    assert ob is not None and ob["kind"] == "event"
