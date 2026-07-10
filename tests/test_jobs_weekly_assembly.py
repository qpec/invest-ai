"""P6.12: the Saturday run end-to-end — numbered message series + sendDocument (tg-spec §2.2),
one context, headline first, EUR total weekly only (§15 A3)."""
from datetime import datetime, timezone

from agentcy import db
from agentcy.clock import FixedClock

SAT = FixedClock(datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc))


def _stub_everything(monkeypatch):
    """Stub the fetch-facing halves already tested in P6.9-P6.11."""
    from agentcy import cluster, study, triggers
    from agentcy.jobs import weekly
    from agentcy.render.contexts import StudyContext
    monkeypatch.setattr(weekly, "refresh_batch",
                        lambda conn, *, run_id, clock, state_dir: {"data_health": [], "spooled": []})
    monkeypatch.setattr(triggers, "evaluate_armed",
                        lambda c, *, cadence, thesis_id=None, as_of, run_id: [])
    monkeypatch.setattr(triggers, "unverifiable_weeks", lambda c, t, *, as_of: 0)
    monkeypatch.setattr(study, "build_digest", lambda c, *, as_of: StudyContext(
        restudy_ticker="MSFT", restudy_excerpt="…", restudy_question="q?",
        mental_model_prompt="Invert.", journal_previews=(), reading_line="10-K §1A",
        circle_note_ask_id=None))
    monkeypatch.setattr(study, "advance_rotation", lambda c, **kw: None)
    import pandas as pd
    from agentcy.cluster import ClusterResult
    monkeypatch.setattr(cluster, "compute_clusters",
                        lambda returns, weights, *, threshold=0.7: ClusterResult(
                            memberships={"MSFT": 1}, cluster_weights={1: 1.0}, n_eff=1.0,
                            corr_matrix=pd.DataFrame(), excluded=(), stale=False))


def _finish_prior_weekly_keys(conn, keep):
    """Steady state: every earlier Saturday already ran, so today's sweep has exactly one
    on-time key (mirrors P6.4's daily helper; without it the 6-week lookback archives all 6)."""
    from agentcy import runlog
    for key in runlog.due_keys("weekly", as_of=SAT.now()):
        if key == keep:
            continue
        h = runlog.start(conn, "weekly", key, clock=SAT)
        runlog.finish(conn, h.run_id, status="ok", outputs={}, clock=SAT)


def test_weekly_run_enqueues_series_and_document(seeded_portfolio, tmp_path, monkeypatch):
    from agentcy.jobs import runner, weekly
    conn = seeded_portfolio["conn"]
    _finish_prior_weekly_keys(conn, keep="2026-07-11")
    _stub_everything(monkeypatch)
    rc = runner.sweep_and_run(conn, "weekly", weekly.run_one, clock=SAT, state_dir=tmp_path)
    assert rc == 0
    assert db.fetch_run(conn, "weekly", "2026-07-11")["status"] == "ok"
    msg1 = db.fetch_outbox_by_key(conn, "weekly:2026-07-11:msg1")
    assert msg1 is not None and msg1["kind"] == "weekly_msg"          # headline first (§2.2)
    doc = db.fetch_outbox_by_key(conn, "weekly:2026-07-11:doc")
    assert doc is not None and doc["kind"] == "weekly_doc" and doc["document_path"]
    reports = db.fetch_reports(conn, type="weekly")
    assert len(reports) == 1                                          # archived once, NFR4 twice over


def test_build_weekly_context_totals_and_sections(seeded_portfolio, monkeypatch):
    from agentcy import runlog
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _stub_everything(monkeypatch)
    rh = runlog.start(conn, "weekly", "2026-07-11", clock=SAT)   # study_block mints an N ask (run_id FK)
    ctx = weekly.build_weekly_context(conn, as_of=SAT.now(), clock=SAT, run_id=rh.run_id,
                                      refresh_notes=["MSFT shares: fetch failed"])
    assert abs(ctx.total_eur - 16500.0) < 1e-6           # 8500 MSFT + 8000 cash: weekly carries value
    assert len(ctx.portfolio) == 1 and ctx.portfolio[0].ticker == "MSFT"
    assert ctx.portfolio[0].mv_eur == 8500.0
    assert ctx.celebrated is True                        # nothing fired, nothing waiting
    assert "MSFT shares: fetch failed" in ctx.data_health
    assert ctx.study.circle_note_ask_id is not None
