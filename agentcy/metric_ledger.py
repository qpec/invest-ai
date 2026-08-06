"""Typed, narrow operations for the Metric Evidence Ledger.

All writes pass through :mod:`agentcy.db`; this module owns domain validation,
transactions, and read models for consumers.
"""
from __future__ import annotations

import math
import sqlite3
from enum import StrEnum
from typing import Iterable

from agentcy import db


class MetricStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"
    UNVERIFIABLE = "UNVERIFIABLE"


def define_metric(conn: sqlite3.Connection, *, metric_key: str, formula_version: str,
                  unit: str, requirement: str, freshness_policy: str, active_from: str,
                  created_at: str, active_until: str | None = None) -> int:
    """Append a metric definition or return its id when replayed."""
    return db.append_metric_definition(conn, {
        "metric_key": metric_key,
        "formula_version": formula_version,
        "unit": unit,
        "requirement": requirement,
        "freshness_policy": freshness_policy,
        "active_from": active_from,
        "active_until": active_until,
        "created_at": created_at,
    })


def append_source_observation(conn: sqlite3.Connection, *, ticker: str, source: str,
                              source_key: str, value: float, unit: str, period_end: str,
                              fetched_at: str, payload_hash: str, accession: str | None = None,
                              currency: str | None = None, period_start: str | None = None,
                              filed_at: str | None = None,
                              refresh_run_id: int | None = None) -> int:
    """Append one finite raw fact or return the id of an exact payload replay."""
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("source observation value must be finite")
    return db.append_source_observation(conn, {
        "ticker": ticker,
        "source": source,
        "source_key": source_key,
        "accession": accession,
        "value": numeric,
        "unit": unit,
        "currency": currency,
        "period_start": period_start,
        "period_end": period_end,
        "filed_at": filed_at,
        "fetched_at": fetched_at,
        "payload_hash": payload_hash,
        "refresh_run_id": refresh_run_id,
    })


def append_metric_observation(conn: sqlite3.Connection, *, metric_definition_id: int,
                              ticker: str, value: float | None, status: MetricStatus | str,
                              confidence: float, as_of: str, calculated_at: str,
                              input_ids: Iterable[int], refresh_run_id: int | None = None,
                              source_policy_id: int | None = None) -> int:
    """Atomically append a derived metric and its exact source lineage."""
    numeric = None if value is None else float(value)
    if numeric is not None and not math.isfinite(numeric):
        raise ValueError("metric observation value must be finite or None")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    source_ids = list(dict.fromkeys(int(item) for item in input_ids))
    with conn:
        metric_id = db.append_metric_observation(conn, {
            "metric_definition_id": metric_definition_id,
            "ticker": ticker,
            "value": numeric,
            "status": MetricStatus(status).value,
            "confidence": confidence,
            "as_of": as_of,
            "calculated_at": calculated_at,
            "refresh_run_id": refresh_run_id,
            "source_policy_id": source_policy_id,
        })
        db.append_metric_inputs(conn, metric_id, source_ids)
    return metric_id


def metric_inputs(conn: sqlite3.Connection, metric_observation_id: int) -> list[int]:
    """Return source observation ids in stable insertion-independent order."""
    return [int(row[0]) for row in conn.execute(
        "SELECT source_observation_id FROM metric_input"
        " WHERE metric_observation_id=? ORDER BY source_observation_id",
        (metric_observation_id,),
    )]


def current_metric(conn: sqlite3.Connection, ticker: str, metric_key: str):
    """Current materialized observation for one ticker and metric, or None."""
    return conn.execute(
        "SELECT * FROM v_current_metric WHERE ticker=? AND metric_key=?",
        (ticker, metric_key),
    ).fetchone()


def stock_health(conn: sqlite3.Connection, ticker: str):
    """Current decision-readiness summary for one ticker, or None."""
    return conn.execute(
        "SELECT * FROM v_stock_data_health WHERE ticker=?", (ticker,)
    ).fetchone()
