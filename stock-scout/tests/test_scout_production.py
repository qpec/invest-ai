import production
import pytest

from agentcy import db


@pytest.fixture()
def production_db(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    yield conn
    conn.close()


def stage_set(calls, artifact):
    def stage(name, result):
        def run(context):
            calls.append(name)
            return result
        return run

    return production.ProductionStages(
        refresh=stage("refresh", {"deep": False}),
        score=stage("score", {"eligible": 0, "rows": []}),
        select_top=stage("select_top", {"members": []}),
        select_lowcap=stage("select_lowcap", {"members": []}),
        evaluate_theses=stage("evaluate_theses", {"evaluations": []}),
        monitor=stage("monitor", {"committed": [], "monitored": []}),
        build_site=stage("build_site", {
            "artifact_path": str(artifact), "manifest_hash": "abc",
            "component_snapshot_ids": [], "public_model": {},
        }),
        validate=stage("validate", {"passed": True, "failed": []}),
        publish=stage("publish", {"commit": "deadbeef"}),
    )


def test_orchestrator_orders_every_stage_and_publishes(production_db, tmp_path):
    calls = []
    result = production.ProductionOrchestrator(
        production_db, stage_set(calls, tmp_path / "artifact"),
        source_commit="source", now=lambda: "2026-08-07T12:00:00Z",
    ).run(mode="manual", run_id="run-1", snapshot_id="snap-1")
    assert result.status == "PUBLISHED"
    assert calls == [
        "refresh", "score", "select_top", "select_lowcap", "evaluate_theses",
        "monitor", "build_site", "validate", "publish",
    ]
    active = production_db.execute(
        "SELECT snapshot_id, published_commit FROM production_snapshot WHERE active=1"
    ).fetchone()
    assert tuple(active) == ("snap-1", "deadbeef")


def test_weekly_sets_deep_on_the_same_path(production_db, tmp_path):
    calls = []
    stages = stage_set(calls, tmp_path / "artifact")
    seen = {}
    original = stages.refresh

    def refresh(context):
        seen["deep"] = context.deep
        return original(context)

    stages = production.ProductionStages(**{**stages.__dict__, "refresh": refresh})
    production.ProductionOrchestrator(
        production_db, stages, source_commit="source",
        now=lambda: "2026-08-07T12:00:00Z",
    ).run(mode="weekly", run_id="run-1", snapshot_id="snap-1")
    assert seen == {"deep": True}
    assert calls[0] == "refresh"


def test_failure_stops_later_stages_and_never_promotes(production_db, tmp_path):
    calls = []
    stages = stage_set(calls, tmp_path / "artifact")

    def score(context):
        calls.append("score")
        raise RuntimeError("scoring exploded")

    stages = production.ProductionStages(**{**stages.__dict__, "score": score})
    result = production.ProductionOrchestrator(
        production_db, stages, source_commit="source",
        now=lambda: "2026-08-07T12:00:00Z",
    ).run(mode="daily", run_id="run-1", snapshot_id="snap-1")
    assert result.status == "FAILED"
    assert result.failure_stage == "score"
    assert calls == ["refresh", "score"]
    assert production_db.execute(
        "SELECT count(*) FROM production_snapshot WHERE active=1").fetchone()[0] == 0


def test_publish_failure_is_retryable_without_recomputation(production_db, tmp_path):
    calls = []
    stages = stage_set(calls, tmp_path / "artifact")

    def broken_publish(context):
        calls.append("publish")
        raise RuntimeError("network down")

    stages = production.ProductionStages(**{**stages.__dict__, "publish": broken_publish})
    orchestrator = production.ProductionOrchestrator(
        production_db, stages, source_commit="source",
        now=lambda: "2026-08-07T12:00:00Z",
    )
    result = orchestrator.run(mode="manual", run_id="run-1", snapshot_id="snap-1")
    assert result.status == "VALIDATED"
    before = list(calls)

    def working_publish(context):
        calls.append("publish-retry")
        assert context.manifest_hash == "abc"
        return {"commit": "deadbeef"}

    retry_stages = production.ProductionStages(
        **{**stages.__dict__, "publish": working_publish})
    retry = production.ProductionOrchestrator(
        production_db, retry_stages, source_commit="source",
        now=lambda: "2026-08-07T12:05:00Z",
    ).retry_publish("run-1")
    assert retry.status == "PUBLISHED"
    assert calls == before + ["publish-retry"]


def test_deferred_publish_stops_after_atomic_promotion(production_db, tmp_path):
    calls = []
    result = production.ProductionOrchestrator(
        production_db, stage_set(calls, tmp_path / "artifact"),
        source_commit="source", now=lambda: "2026-08-07T12:00:00Z",
        defer_publish=True,
    ).run(mode="manual", run_id="run-1", snapshot_id="snap-1")
    assert result.status == "VALIDATED"
    assert calls[-1] == "validate"
    assert "publish" not in calls
    assert production_db.execute(
        "SELECT active FROM production_snapshot WHERE snapshot_id='snap-1'"
    ).fetchone()[0] == 1


def test_lowcap_members_land_append_only_per_lens(production_db, tmp_path):
    """The lane's selection (2026-08-14 design) rides the same run in its OWN table:
    rank is scoped per lens (four lists, never merged), Forged-out names never reach
    it, and the append-only triggers hold."""
    calls = []
    stages = stage_set(calls, tmp_path / "artifact")
    members = [
        {"lens": "downside", "security_key": "AAA", "symbol": "AAA", "rank": 1,
         "forge_verdict": "Survivor"},
        {"lens": "garp", "security_key": "AAA", "symbol": "AAA", "rank": 1,
         "forge_verdict": "Survivor"},
        {"lens": "garp", "security_key": "BBB", "symbol": "BBB", "rank": 2,
         "forge_verdict": "Watch"},
    ]
    stages = production.ProductionStages(**{
        **stages.__dict__,
        "select_lowcap": lambda context: {"members": list(members)}})
    result = production.ProductionOrchestrator(
        production_db, stages, source_commit="source",
        now=lambda: "2026-08-14T12:00:00Z",
    ).run(mode="manual", run_id="run-1", snapshot_id="snap-1")
    assert result.status == "PUBLISHED"
    rows = production_db.execute(
        "SELECT lens, symbol, rank, forge_verdict FROM production_lowcap_member"
        " ORDER BY lens, rank").fetchall()
    assert [tuple(r) for r in rows] == [
        ("downside", "AAA", 1, "Survivor"),
        ("garp", "AAA", 1, "Survivor"), ("garp", "BBB", 2, "Watch"),
    ]
    import pytest as _pytest
    with _pytest.raises(Exception, match="append-only"):
        production_db.execute("DELETE FROM production_lowcap_member")
    with _pytest.raises(Exception):
        production_db.execute(
            "INSERT INTO production_lowcap_member"
            " (run_id, lens, security_key, symbol, rank, forge_verdict)"
            " VALUES ('run-1', 'garp', 'CCC', 'CCC', 3, 'Forged-out')")


def test_a_default_stage_set_records_an_explicitly_empty_lane(production_db, tmp_path):
    """ProductionStages without select_lowcap (pre-lane constructions) still runs: the
    default stage records an empty selection rather than crashing or skipping."""
    calls = []
    base = stage_set(calls, tmp_path / "artifact")
    fields = {k: v for k, v in base.__dict__.items() if k != "select_lowcap"}
    stages = production.ProductionStages(**fields)
    result = production.ProductionOrchestrator(
        production_db, stages, source_commit="source",
        now=lambda: "2026-08-14T12:00:00Z",
    ).run(mode="manual", run_id="run-1", snapshot_id="snap-1")
    assert result.status == "PUBLISHED"
    assert production_db.execute(
        "SELECT count(*) FROM production_lowcap_member").fetchone()[0] == 0
