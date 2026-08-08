from pathlib import Path

import pytest

from agentcy import production


def valid_readers():
    base = {
        "logo": None,
        "thesis": {"business_model": "A", "bear_case": "B",
                   "valuation_anchor": {"statement": "V"}, "triggers": []},
        "quality": {"score": 90, "grade": "Exceptional"},
        "risk": {"verdict": "Ordinary", "leading_fragility": "F"},
        "valuation_lens": {
            "price": 25.5, "price_as_of": "2026-08-06",
            "owner_cash_yield_pct": 8.0, "owner_cash_multiple_x": 12.5,
            "comparison_scope": "sector", "comparison_label": "IT sector",
            "comparison_count": 42, "percentile": 83,
            "signal": "Appears inexpensive on current owner cash flow",
            "caveat": "Cash flow may normalize.",
        },
        "summary_html": "<p>S</p>", "report_html": "<p>R</p>",
        "triggers": [],
    }
    return [dict(base, symbol="AAA", rank=1),
            dict(base, symbol="BBB", rank=2, logo="data/logos/BBB.png")]


def valid_release(**overrides):
    values = dict(
        snapshot_id="snap-1",
        eligible=200,
        top_members=2,
        committed_symbols=frozenset({"AAA"}),
        monitored_symbols=frozenset({"AAA"}),
        component_snapshot_ids=frozenset({"snap-1"}),
        public_model={"portfolio_monitor": [{"symbol": "AAA"}],
                      "thesis": {"readers": valid_readers()}},
        index_exists=True,
        manifest_exists=True,
        data_quality_passed=True,
        thesis_evaluations_passed=True,
    )
    values.update(overrides)
    return production.ReleaseInput(**values)


def test_validate_requires_exact_top_fraction():
    result = production.validate_release(valid_release(top_members=1))
    assert not result.passed
    assert not result.checks["top_fraction_exact"]


def test_validate_requires_monitor_result_for_every_committed_thesis():
    result = production.validate_release(valid_release(monitored_symbols=frozenset()))
    assert not result.checks["all_committed_monitored"]


def test_validate_rejects_mixed_snapshot_ids():
    result = production.validate_release(valid_release(
        component_snapshot_ids=frozenset({"snap-1", "snap-old"})))
    assert not result.checks["single_snapshot"]


def test_validate_rejects_failed_top_thesis_evaluation():
    result = production.validate_release(valid_release(
        thesis_evaluations_passed=False))
    assert not result.checks["thesis_evaluations_passed"]


@pytest.mark.parametrize("mutation,check", [
    ("missing_reader", "top_thesis_readers_complete"),
    ("duplicate_rank", "top_thesis_reader_routes_unique"),
    ("missing_section", "top_thesis_reader_sections_complete"),
    ("external_logo", "top_thesis_reader_logos_local"),
])
def test_release_rejects_invalid_public_reader_model(mutation, check):
    readers = valid_readers()
    if mutation == "missing_reader":
        readers.pop()
    elif mutation == "duplicate_rank":
        readers[1]["rank"] = 1
    elif mutation == "missing_section":
        readers[1]["thesis"] = dict(readers[1]["thesis"])
        readers[1]["thesis"].pop("bear_case")
    elif mutation == "external_logo":
        readers[1]["logo"] = "https://example.com/logo.png"
    model = {"portfolio_monitor": [], "thesis": {"readers": readers}}

    result = production.validate_release(valid_release(public_model=model))

    assert not result.checks[check]


@pytest.mark.parametrize("field", [
    "price", "price_as_of", "owner_cash_yield_pct", "owner_cash_multiple_x",
    "comparison_scope", "comparison_label", "comparison_count", "percentile",
    "signal", "caveat",
])
def test_release_rejects_incomplete_reader_valuation(field):
    readers = valid_readers()
    readers[0]["valuation_lens"] = dict(readers[0]["valuation_lens"])
    readers[0]["valuation_lens"].pop(field)
    model = {"portfolio_monitor": [], "thesis": {"readers": readers}}
    result = production.validate_release(valid_release(public_model=model))
    assert not result.checks["top_thesis_reader_valuations_complete"]


@pytest.mark.parametrize(("field", "value"), [
    ("price", 0), ("owner_cash_yield_pct", 0), ("percentile", 101),
    ("comparison_count", 0), ("comparison_scope", "peers"),
])
def test_release_rejects_invalid_reader_valuation(field, value):
    readers = valid_readers()
    readers[0]["valuation_lens"] = dict(readers[0]["valuation_lens"], **{field: value})
    model = {"portfolio_monitor": [], "thesis": {"readers": readers}}
    result = production.validate_release(valid_release(public_model=model))
    assert not result.checks["top_thesis_reader_valuations_complete"]


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
