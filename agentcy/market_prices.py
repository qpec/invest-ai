"""Resumable provider-neutral market-price evidence refresh."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from agentcy import db
from agentcy.fetch import yf as fetch_yf


@dataclass(frozen=True)
class RefreshSummary:
    run_id: int
    status: str
    selected: int
    completed: int
    remaining: int
    ok: int
    terminal: int
    failed: int


def observation_hash(row: dict) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def freshness_status(bar_date: str, as_of: datetime, *, max_age_days: int = 45) -> str:
    age = (as_of.date() - date.fromisoformat(bar_date)).days
    return "FRESH" if 0 <= age <= max_age_days else "STALE"


def _iso(moment: datetime) -> str:
    return db.to_iso(moment)


def _start_run(conn: sqlite3.Connection, *, scheduled_for: str, started_at: str,
               selected_count: int) -> int:
    attempt = int(conn.execute(
        "SELECT COALESCE(MAX(attempt), 0) + 1 FROM market_price_refresh_run"
        " WHERE scheduled_for=?", (scheduled_for,)
    ).fetchone()[0])
    return db.append_market_price_run(conn, {
        "scheduled_for": scheduled_for,
        "attempt": attempt,
        "started_at": started_at,
        "status": "RUNNING",
        "selected_count": selected_count,
    })


def _latest_outcomes(conn: sqlite3.Connection, run_id: int) -> dict[tuple[str, str], str]:
    rows = conn.execute(
        "SELECT security_key, provider_symbol, outcome FROM ("
        " SELECT *, ROW_NUMBER() OVER (PARTITION BY security_key, provider_symbol"
        " ORDER BY attempt_no DESC, price_attempt_id DESC) rank"
        " FROM market_price_attempt WHERE refresh_run_id=?"
        ") WHERE rank=1", (run_id,)
    )
    return {(row["security_key"], row["provider_symbol"]): row["outcome"] for row in rows}


def _attempt_no(conn: sqlite3.Connection, run_id: int, security_key: str) -> int:
    return int(conn.execute(
        "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM market_price_attempt"
        " WHERE refresh_run_id=? AND security_key=?", (run_id, security_key)
    ).fetchone()[0])


def _append_attempt(conn, *, run_id: int, security_key: str, symbol: str,
                    attempted_at: str, outcome: str, reason: str | None = None,
                    detail: str | None = None) -> None:
    db.append_market_price_attempt(conn, {
        "refresh_run_id": run_id,
        "security_key": security_key,
        "provider_symbol": symbol,
        "attempt_no": _attempt_no(conn, run_id, security_key),
        "attempted_at": attempted_at,
        "outcome": outcome,
        "reason_code": reason,
        "detail": detail,
    })


def _append_frame(conn, *, run_id: int, security_key: str, symbol: str,
                  frame: pd.DataFrame, fetched_at: str) -> None:
    latest = frame.index.max()
    retained = frame[(frame.index == latest) | (frame["split"].astype(float) > 0)]
    for index, values in retained.iterrows():
        split = float(values["split"])
        evidence = {
            "security_key": security_key,
            "provider": "yahoo",
            "provider_symbol": symbol,
            "bar_date": pd.Timestamp(index).date().isoformat(),
            "raw_close": float(values["close"]),
            "adjusted_close": float(values["adj_close"]),
            "dividend": float(values["dividend"]),
            "split_ratio": split if split > 0 else None,
            "currency": str(values["currency"]),
        }
        db.append_market_price_observation(conn, {
            "refresh_run_id": run_id,
            **evidence,
            "fetched_at": fetched_at,
            "payload_hash": observation_hash(evidence),
        })


def _summary(conn, run_id: int, *, status: str | None = None) -> RefreshSummary:
    run = conn.execute(
        "SELECT * FROM market_price_refresh_run WHERE refresh_run_id=?", (run_id,)
    ).fetchone()
    outcomes = _latest_outcomes(conn, run_id)
    ok = sum(value == "OK" for value in outcomes.values())
    terminal = sum(value in {"NO_DATA", "TERMINAL"} for value in outcomes.values())
    failed = sum(value in {"FAILED", "RATE_LIMITED"} for value in outcomes.values())
    completed = ok + terminal
    selected = int(run["selected_count"])
    return RefreshSummary(run_id, status or run["status"], selected, completed,
                          max(0, selected - completed), ok, terminal, failed)


def refresh(conn: sqlite3.Connection, *, state_dir: Path, now: datetime,
            scheduled_for: str, budget: int, chunk_size: int = 50,
            resume_run_id: int | None = None,
            fetch_batch: Callable = fetch_yf.fetch_daily_bars_batch) -> RefreshSummary:
    """Process at most budget unresolved eligible securities and promote only at zero remaining."""
    securities = [dict(row) for row in conn.execute(
        "SELECT security_key, symbol, currency FROM v_eligible_security"
        " ORDER BY symbol"
    )]
    if resume_run_id is None:
        with conn:
            run_id = _start_run(conn, scheduled_for=scheduled_for,
                                started_at=_iso(now), selected_count=len(securities))
    else:
        run_id = int(resume_run_id)
        run = conn.execute(
            "SELECT * FROM market_price_refresh_run WHERE refresh_run_id=?", (run_id,)
        ).fetchone()
        if run is None or run["status"] not in {"RUNNING", "DEGRADED"}:
            raise ValueError("resume run must exist and be RUNNING or DEGRADED")
        if int(run["selected_count"]) != len(securities):
            raise ValueError("eligible universe changed; start a new price refresh")
        if run["status"] == "DEGRADED":
            conn.execute(
                "UPDATE market_price_refresh_run SET status='RUNNING', finished_at=NULL,"
                " failure_summary=NULL WHERE refresh_run_id=?", (run_id,)
            )
            conn.commit()

    outcomes = _latest_outcomes(conn, run_id)
    done = {key for key, outcome in outcomes.items()
            if outcome in {"OK", "NO_DATA", "TERMINAL"}}
    pending = [row for row in securities
               if (row["security_key"], row["symbol"]) not in done]
    work = pending[:max(0, int(budget))]

    for offset in range(0, len(work), max(1, int(chunk_size))):
        chunk = work[offset:offset + max(1, int(chunk_size))]
        symbols = [row["symbol"] for row in chunk]
        currencies = {row["symbol"]: row["currency"] for row in chunk}
        try:
            frames, failures = fetch_batch(
                symbols, currencies=currencies, state_dir=Path(state_dir), period="2y"
            )
        except fetch_yf.RateLimited as error:
            with conn:
                for row in chunk:
                    _append_attempt(conn, run_id=run_id, security_key=row["security_key"],
                                    symbol=row["symbol"], attempted_at=_iso(now),
                                    outcome="RATE_LIMITED", reason="RATE_LIMITED",
                                    detail=str(error))
                current = _summary(conn, run_id, status="DEGRADED")
                db.finish_market_price_run(
                    conn, run_id, finished_at=_iso(now), status="DEGRADED",
                    ok_count=current.ok, terminal_count=current.terminal,
                    failed_count=current.failed, failure_summary=str(error), promoted=False,
                )
            return _summary(conn, run_id)

        by_symbol = {row["symbol"]: row for row in chunk}
        with conn:
            for symbol, frame in frames.items():
                row = by_symbol[symbol]
                _append_frame(conn, run_id=run_id, security_key=row["security_key"],
                              symbol=symbol, frame=frame, fetched_at=_iso(now))
                _append_attempt(conn, run_id=run_id, security_key=row["security_key"],
                                symbol=symbol, attempted_at=_iso(now), outcome="OK")
            for symbol, reason in failures.items():
                row = by_symbol[symbol]
                outcome = "NO_DATA" if reason == "NO_DATA" else "TERMINAL"
                _append_attempt(conn, run_id=run_id, security_key=row["security_key"],
                                symbol=symbol, attempted_at=_iso(now), outcome=outcome,
                                reason=reason)

    result = _summary(conn, run_id)
    if result.remaining == 0:
        with conn:
            db.finish_market_price_run(
                conn, run_id, finished_at=_iso(now), status="SUCCEEDED",
                ok_count=result.ok, terminal_count=result.terminal,
                failed_count=result.failed, promoted=True,
            )
        return _summary(conn, run_id)
    return result


def status_summary(conn: sqlite3.Connection, *, as_of: datetime) -> dict:
    """Machine-readable state of the latest promoted local price snapshot."""
    eligible = int(conn.execute("SELECT COUNT(*) FROM v_eligible_security").fetchone()[0])
    rows = list(conn.execute("SELECT * FROM v_current_market_price"))
    fresh = sum(freshness_status(row["bar_date"], as_of) == "FRESH" for row in rows)
    stale = len(rows) - fresh
    run = conn.execute(
        "SELECT * FROM market_price_refresh_run"
        " WHERE status='SUCCEEDED' AND promoted=1"
        " ORDER BY scheduled_for DESC, attempt DESC, refresh_run_id DESC LIMIT 1"
    ).fetchone()
    terminal = 0
    if run is not None:
        outcomes = _latest_outcomes(conn, int(run["refresh_run_id"]))
        terminal = sum(value in {"NO_DATA", "TERMINAL"} for value in outcomes.values())
    providers: dict[str, int] = {}
    for row in rows:
        providers[row["provider"]] = providers.get(row["provider"], 0) + 1
    return {
        "schema_version": 1,
        "generated_at": _iso(as_of),
        "refresh_run_id": int(run["refresh_run_id"]) if run is not None else None,
        "eligible": eligible,
        "fresh": fresh,
        "stale": stale,
        "missing": max(0, eligible - len(rows) - terminal),
        "terminal": terminal,
        "conflict": 0,
        "providers": dict(sorted(providers.items())),
    }
