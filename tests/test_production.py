from pathlib import Path

import pytest

from agentcy import production


def valid_release(**overrides):
    values = dict(
        snapshot_id="snap-1",
        eligible=200,
        top_members=2,
        committed_symbols=frozenset({"AAA"}),
        monitored_symbols=frozenset({"AAA"}),
        component_snapshot_ids=frozenset({"snap-1"}),
        public_model={"portfolio_monitor": [{"symbol": "AAA"}]},
        index_exists=True,
        manifest_exists=True,
        data_quality_passed=True,
    )
    values.update(overrides)
    return production.ReleaseInput(**values)


def test_validate_requires_exact_top_fraction():
    result = production.validate_release(valid_release(top_members=1))
    assert not result.passed
    assert result.failed == ("top_fraction_exact",)


def test_validate_requires_monitor_result_for_every_committed_thesis():
    result = production.validate_release(valid_release(monitored_symbols=frozenset()))
    assert not result.checks["all_committed_monitored"]


def test_validate_rejects_mixed_snapshot_ids():
    result = production.validate_release(valid_release(
        component_snapshot_ids=frozenset({"snap-1", "snap-old"})))
    assert not result.checks["single_snapshot"]


@pytest.mark.parametrize("field", sorted(production.PRIVATE_FIELDS))
def test_validate_rejects_private_public_fields_at_any_depth(field):
    model = {"portfolio_monitor": [{"symbol": "AAA", "nested": {field: "secret"}}]}
    result = production.validate_release(valid_release(public_model=model))
    assert not result.checks["public_fields_safe"]


def _start_and_validate(conn, run_id="run-1"):
    production.start_run(
        conn, run_id=run_id, mode="manual", source_commit="abc123",
        started_at="2026-08-07T12:00:00Z")
    production.validate_run(conn, run_id, finished_at="2026-08-07T12:01:00Z")


def test_failed_run_cannot_promote(tmp_db, tmp_path):
    production.start_run(
        tmp_db, run_id="run-1", mode="manual", source_commit="abc123",
        started_at="2026-08-07T12:00:00Z")
    production.fail_run(
        tmp_db, "run-1", stage="score", reason="broken",
        finished_at="2026-08-07T12:01:00Z")
    production.stage_snapshot(
        tmp_db, snapshot_id="snap-1", run_id="run-1", manifest_hash="hash",
        artifact_path=tmp_path / "snap-1", created_at="2026-08-07T12:01:00Z")
    with pytest.raises(ValueError, match="VALIDATED"):
        production.promote_snapshot(tmp_db, "snap-1")


def test_promotion_deactivates_previous_snapshot_atomically(tmp_db, tmp_path):
    _start_and_validate(tmp_db, "run-1")
    production.stage_snapshot(
        tmp_db, snapshot_id="snap-1", run_id="run-1", manifest_hash="hash-1",
        artifact_path=tmp_path / "snap-1", created_at="2026-08-07T12:01:00Z")
    production.promote_snapshot(tmp_db, "snap-1")

    _start_and_validate(tmp_db, "run-2")
    production.stage_snapshot(
        tmp_db, snapshot_id="snap-2", run_id="run-2", manifest_hash="hash-2",
        artifact_path=tmp_path / "snap-2", created_at="2026-08-07T12:02:00Z")
    production.promote_snapshot(tmp_db, "snap-2")

    rows = tmp_db.execute(
        "SELECT snapshot_id, active FROM production_snapshot ORDER BY snapshot_id"
    ).fetchall()
    assert [(r["snapshot_id"], r["active"]) for r in rows] == [
        ("snap-1", 0), ("snap-2", 1)]


def test_record_published_commit_is_idempotent(tmp_db, tmp_path):
    _start_and_validate(tmp_db)
    production.stage_snapshot(
        tmp_db, snapshot_id="snap-1", run_id="run-1", manifest_hash="hash",
        artifact_path=Path(tmp_path) / "snap-1", created_at="2026-08-07T12:01:00Z")
    production.promote_snapshot(tmp_db, "snap-1")
    production.record_published_commit(
        tmp_db, "snap-1", "deadbeef", finished_at="2026-08-07T12:02:00Z")
    production.record_published_commit(
        tmp_db, "snap-1", "deadbeef", finished_at="2026-08-07T12:02:00Z")
    row = tmp_db.execute(
        "SELECT status, published_commit FROM production_run JOIN production_snapshot"
        " USING(run_id) WHERE snapshot_id='snap-1'"
    ).fetchone()
    assert tuple(row) == ("PUBLISHED", "deadbeef")
