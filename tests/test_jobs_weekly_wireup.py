"""P6.14: weekly run_one wires the halves in order; Study digest folds in; one document + series."""
from datetime import datetime, timezone

from agentcy import db, runlog
from agentcy.clock import FixedClock
from agentcy.jobs import runner

SAT = FixedClock(datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc))


def _stub_all(monkeypatch):
    """Neutralize network + heavy sub-steps so run_one's SEQUENCING is what we test."""
    from agentcy.jobs import weekly
    monkeypatch.setattr(weekly, "refresh_batch",
                        lambda conn, *, run_id, clock, state_dir: {"data_health": [], "spooled": []})
    monkeypatch.setattr(weekly, "run_trigger_tests",
                        lambda conn, *, run_id, clock: {"fired_alert_ids": [], "outcome_counts": {}})
    monkeypatch.setattr(weekly, "queue_prompted_questions",
                        lambda conn, *, run_id, clock: [])


def _finish_prior_weekly_keys(conn, keep):
    """Steady state: every earlier Saturday already ran, so today's sweep has exactly one
    on-time key (mirrors P6.12's assembly helper; without it the 6-week lookback archives all 6)."""
    for key in runlog.due_keys("weekly", as_of=SAT.now()):
        if key == keep:
            continue
        h = runlog.start(conn, "weekly", key, clock=SAT)
        runlog.finish(conn, h.run_id, status="ok", outputs={}, clock=SAT)


def test_run_one_produces_series_and_document(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _finish_prior_weekly_keys(conn, keep="2026-07-11")
    _stub_all(monkeypatch)
    rc = runner.sweep_and_run(conn, "weekly", weekly.run_one, clock=SAT, state_dir=tmp_path)
    assert rc == 0
    assert db.fetch_run(conn, "weekly", "2026-07-11")["status"] == "ok"
    # headline message under msg1, full document under doc:
    assert db.fetch_outbox_by_key(conn, "weekly:2026-07-11:msg1") is not None
    doc = db.fetch_outbox_by_key(conn, "weekly:2026-07-11:doc")
    assert doc is not None and doc["kind"] == "weekly_doc" and doc["document_path"]
    # a weekly report row archived:
    assert len(db.fetch_reports(conn, type="weekly")) == 1


def test_study_digest_advances_rotation_pointer(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _finish_prior_weekly_keys(conn, keep="2026-07-11")
    _stub_all(monkeypatch)
    before = db.fetch_study_state(conn)["mental_model_index"]
    runner.sweep_and_run(conn, "weekly", weekly.run_one, clock=SAT, state_dir=tmp_path)
    after = db.fetch_study_state(conn)["mental_model_index"]
    assert after != before                                  # study.advance_rotation ran (F.3)
