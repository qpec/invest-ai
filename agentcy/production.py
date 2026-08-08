"""Atomic production-snapshot state and release validation."""
from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentcy import db


PRIVATE_FIELDS = frozenset({
    "quantity", "shares", "cost_basis", "average_price", "market_value",
    "account_id", "account_name",
})


@dataclass(frozen=True)
class ReleaseInput:
    snapshot_id: str
    eligible: int
    top_members: int
    committed_symbols: frozenset[str]
    monitored_symbols: frozenset[str]
    component_snapshot_ids: frozenset[str]
    public_model: dict[str, Any]
    index_exists: bool
    manifest_exists: bool
    data_quality_passed: bool
    thesis_evaluations_passed: bool = True


@dataclass(frozen=True)
class ReleaseResult:
    passed: bool
    checks: dict[str, bool]
    failed: tuple[str, ...]


def _contains_private_field(value: Any) -> bool:
    if isinstance(value, dict):
        if PRIVATE_FIELDS.intersection(value):
            return True
        return any(_contains_private_field(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_private_field(item) for item in value)
    return False


def _public_readers(model: dict[str, Any]) -> list[dict[str, Any]]:
    readers = (model.get("thesis") or {}).get("readers") or []
    return readers if isinstance(readers, list) else []


def _reader_routes_unique(readers: list[dict[str, Any]]) -> bool:
    symbols = [reader.get("symbol") for reader in readers]
    ranks = [reader.get("rank") for reader in readers]
    return (all(isinstance(symbol, str) and
                re.fullmatch(r"[A-Z0-9.-]{1,15}", symbol) for symbol in symbols)
            and len(symbols) == len(set(symbols))
            and all(isinstance(rank, int) for rank in ranks)
            and set(ranks) == set(range(1, len(readers) + 1)))


def _reader_sections_complete(readers: list[dict[str, Any]]) -> bool:
    for reader in readers:
        thesis = reader.get("thesis") or {}
        quality = reader.get("quality") or {}
        risk = reader.get("risk") or {}
        if not (thesis.get("business_model") and thesis.get("bear_case")
                and (thesis.get("valuation_anchor") or {}).get("statement")
                and quality.get("grade") and risk.get("verdict")
                and "summary_html" in reader and "report_html" in reader
                and isinstance(reader.get("triggers"), list)):
            return False
    return True


def _reader_logos_local(readers: list[dict[str, Any]]) -> bool:
    for reader in readers:
        logo = reader.get("logo")
        if logo is None:
            continue
        if (not isinstance(logo, str) or not logo.startswith("data/logos/")
                or ".." in Path(logo).parts or "://" in logo):
            return False
    return True


def _reader_valuations_complete(readers: list[dict[str, Any]]) -> bool:
    for reader in readers:
        lens = reader.get("valuation_lens") or {}
        price = lens.get("price")
        yield_pct = lens.get("owner_cash_yield_pct")
        multiple = lens.get("owner_cash_multiple_x")
        percentile = lens.get("percentile")
        count = lens.get("comparison_count")
        if not (isinstance(price, (int, float)) and not isinstance(price, bool)
                and math.isfinite(price) and price > 0
                and isinstance(yield_pct, (int, float)) and not isinstance(yield_pct, bool)
                and math.isfinite(yield_pct) and yield_pct > 0
                and isinstance(multiple, (int, float)) and not isinstance(multiple, bool)
                and math.isfinite(multiple) and multiple > 0
                and isinstance(percentile, int) and not isinstance(percentile, bool)
                and 0 <= percentile <= 100
                and isinstance(count, int) and not isinstance(count, bool) and count > 0
                and lens.get("comparison_scope") in {"sector", "universe"}
                and isinstance(lens.get("price_as_of"), str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", lens["price_as_of"])
                and isinstance(lens.get("comparison_label"), str)
                and lens["comparison_label"].strip()
                and isinstance(lens.get("signal"), str) and lens["signal"].strip()
                and isinstance(lens.get("caveat"), str) and lens["caveat"].strip()):
            return False
    return True


def validate_release(value: ReleaseInput) -> ReleaseResult:
    expected_top = max(1, math.ceil(value.eligible * 0.01)) if value.eligible else 0
    readers = _public_readers(value.public_model)
    checks = {
        "top_fraction_exact": value.top_members == expected_top,
        "all_committed_monitored": value.committed_symbols == value.monitored_symbols,
        "single_snapshot": value.component_snapshot_ids == {value.snapshot_id},
        "public_fields_safe": not _contains_private_field(value.public_model),
        "site_complete": value.index_exists and value.manifest_exists,
        "data_quality_passed": value.data_quality_passed,
        "thesis_evaluations_passed": value.thesis_evaluations_passed,
        "top_thesis_readers_complete": len(readers) == value.top_members,
        "top_thesis_reader_routes_unique": _reader_routes_unique(readers),
        "top_thesis_reader_sections_complete": _reader_sections_complete(readers),
        "top_thesis_reader_logos_local": _reader_logos_local(readers),
        "top_thesis_reader_valuations_complete": _reader_valuations_complete(readers),
    }
    failed = tuple(name for name, passed in checks.items() if not passed)
    return ReleaseResult(passed=not failed, checks=checks, failed=failed)


def start_run(conn: sqlite3.Connection, *, run_id: str, mode: str,
              source_commit: str, started_at: str) -> None:
    db.append_production_run(conn, {
        "run_id": run_id, "mode": mode, "status": "RUNNING",
        "source_commit": source_commit, "started_at": started_at,
    })
    conn.commit()


def _run_status(conn: sqlite3.Connection, run_id: str) -> str:
    row = conn.execute(
        "SELECT status FROM production_run WHERE run_id=?", (run_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown production run {run_id}")
    return str(row["status"])


def fail_run(conn: sqlite3.Connection, run_id: str, *, stage: str, reason: str,
             finished_at: str) -> None:
    status = _run_status(conn, run_id)
    if status == "FAILED":
        return
    if status != "RUNNING":
        raise ValueError(f"cannot fail production run in status {status}")
    conn.execute(
        "UPDATE production_run SET status='FAILED', finished_at=?, failure_stage=?,"
        " failure_reason=? WHERE run_id=?",
        (finished_at, stage, reason, run_id),
    )
    conn.commit()


def validate_run(conn: sqlite3.Connection, run_id: str, *, finished_at: str) -> None:
    status = _run_status(conn, run_id)
    if status == "VALIDATED":
        return
    if status != "RUNNING":
        raise ValueError(f"cannot validate production run in status {status}")
    conn.execute(
        "UPDATE production_run SET status='VALIDATED', finished_at=? WHERE run_id=?",
        (finished_at, run_id),
    )
    conn.commit()


def stage_snapshot(conn: sqlite3.Connection, *, snapshot_id: str, run_id: str,
                   manifest_hash: str, artifact_path: Path, created_at: str) -> None:
    db.append_production_snapshot(conn, {
        "snapshot_id": snapshot_id, "run_id": run_id,
        "manifest_hash": manifest_hash, "artifact_path": str(artifact_path),
        "created_at": created_at, "active": 0, "published_commit": None,
    })
    conn.commit()


def promote_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> None:
    row = conn.execute(
        "SELECT ps.active, pr.status FROM production_snapshot ps"
        " JOIN production_run pr USING(run_id) WHERE ps.snapshot_id=?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown production snapshot {snapshot_id}")
    if row["status"] != "VALIDATED":
        raise ValueError("production snapshot run must be VALIDATED before promotion")
    if row["active"]:
        return
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE production_snapshot SET active=0 WHERE active=1")
        conn.execute(
            "UPDATE production_snapshot SET active=1 WHERE snapshot_id=?", (snapshot_id,)
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def record_published_commit(conn: sqlite3.Connection, snapshot_id: str,
                            commit: str, *, finished_at: str) -> None:
    row = conn.execute(
        "SELECT ps.published_commit, pr.run_id, pr.status"
        " FROM production_snapshot ps JOIN production_run pr USING(run_id)"
        " WHERE ps.snapshot_id=? AND ps.active=1",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ValueError("only the active production snapshot can be published")
    if row["published_commit"] == commit and row["status"] == "PUBLISHED":
        return
    if row["status"] != "VALIDATED":
        raise ValueError(f"cannot publish production run in status {row['status']}")
    conn.execute(
        "UPDATE production_snapshot SET published_commit=? WHERE snapshot_id=?",
        (commit, snapshot_id),
    )
    conn.execute(
        "UPDATE production_run SET status='PUBLISHED', finished_at=? WHERE run_id=?",
        (finished_at, row["run_id"]),
    )
    conn.commit()


def record_publication_failure(conn: sqlite3.Connection, run_id: str, *, reason: str,
                               finished_at: str) -> None:
    if _run_status(conn, run_id) != "VALIDATED":
        raise ValueError("only a VALIDATED run can record a publication failure")
    conn.execute(
        "UPDATE production_run SET finished_at=?, failure_stage='publish',"
        " failure_reason=? WHERE run_id=?",
        (finished_at, reason, run_id),
    )
    conn.commit()
