"""Behavior of the narrow Metric Evidence Ledger API."""
from __future__ import annotations

from agentcy import db
from agentcy import metric_ledger as ledger


def _conn(tmp_path):
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    return conn


def _definition(conn, key="owner_fcf_margin_pct", requirement="REQUIRED"):
    return ledger.define_metric(
        conn,
        metric_key=key,
        formula_version="v1",
        unit="%",
        requirement=requirement,
        freshness_policy="filing_aware",
        active_from="2026-08-06",
        created_at="2026-08-06T06:00:00Z",
    )


def _source(conn, *, key, value, payload_hash):
    return ledger.append_source_observation(
        conn,
        ticker="ACME",
        source="sec",
        source_key=key,
        value=value,
        unit="USD",
        period_end="2026-06-30",
        filed_at="2026-08-01T10:00:00Z",
        fetched_at="2026-08-01T11:00:00Z",
        payload_hash=payload_hash,
    )


def test_duplicate_definition_and_source_are_idempotent(tmp_path):
    conn = _conn(tmp_path)
    first_definition = _definition(conn)
    second_definition = _definition(conn)
    first_source = _source(conn, key="Revenue", value=100.0, payload_hash="rev-v1")
    second_source = _source(conn, key="Revenue", value=100.0, payload_hash="rev-v1")

    assert second_definition == first_definition
    assert second_source == first_source
    assert conn.execute("SELECT COUNT(*) FROM metric_definition").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM source_observation").fetchone()[0] == 1


def test_metric_observation_retains_exact_input_lineage(tmp_path):
    conn = _conn(tmp_path)
    definition_id = _definition(conn)
    revenue = _source(conn, key="Revenue", value=100.0, payload_hash="rev-v1")
    owner_fcf = _source(conn, key="OwnerFCF", value=18.2, payload_hash="fcf-v1")

    metric_id = ledger.append_metric_observation(
        conn,
        metric_definition_id=definition_id,
        ticker="ACME",
        value=18.2,
        status=ledger.MetricStatus.FRESH,
        confidence=1.0,
        as_of="2026-06-30",
        calculated_at="2026-08-01T11:01:00Z",
        input_ids=[revenue, owner_fcf],
    )

    assert ledger.metric_inputs(conn, metric_id) == [revenue, owner_fcf]


def test_newest_metric_is_current_and_required_stale_blocks_readiness(tmp_path):
    conn = _conn(tmp_path)
    definition_id = _definition(conn)
    ledger.append_metric_observation(
        conn, metric_definition_id=definition_id, ticker="ACME", value=18.2,
        status=ledger.MetricStatus.FRESH, confidence=1.0, as_of="2026-03-31",
        calculated_at="2026-05-01T11:00:00Z", input_ids=[])
    latest = ledger.append_metric_observation(
        conn, metric_definition_id=definition_id, ticker="ACME", value=17.0,
        status=ledger.MetricStatus.STALE, confidence=0.5, as_of="2026-06-30",
        calculated_at="2026-08-01T11:00:00Z", input_ids=[])

    current = ledger.current_metric(conn, "ACME", "owner_fcf_margin_pct")
    health = ledger.stock_health(conn, "ACME")

    assert current["metric_observation_id"] == latest
    assert current["status"] == "STALE"
    assert health["required_unusable"] == 1
    assert health["decision_ready"] == 0


def test_optional_missing_does_not_block_decision_readiness(tmp_path):
    conn = _conn(tmp_path)
    required = _definition(conn)
    optional = _definition(conn, key="rd_intensity_pct", requirement="OPTIONAL")
    ledger.append_metric_observation(
        conn, metric_definition_id=required, ticker="ACME", value=18.2,
        status=ledger.MetricStatus.FRESH, confidence=1.0, as_of="2026-06-30",
        calculated_at="2026-08-01T11:00:00Z", input_ids=[])
    ledger.append_metric_observation(
        conn, metric_definition_id=optional, ticker="ACME", value=None,
        status=ledger.MetricStatus.MISSING, confidence=0.0, as_of="2026-06-30",
        calculated_at="2026-08-01T11:00:00Z", input_ids=[])

    health = ledger.stock_health(conn, "ACME")

    assert health["optional_unusable"] == 1
    assert health["decision_ready"] == 1
