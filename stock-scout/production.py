"""One fail-atomic Scout -> thesis -> portfolio monitor -> Pages production run."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agentcy import db
from agentcy import production as state


Stage = Callable[["ProductionContext"], dict[str, Any]]


@dataclass(frozen=True)
class ProductionStages:
    refresh: Stage
    score: Stage
    select_top: Stage
    evaluate_theses: Stage
    monitor: Stage
    build_site: Stage
    validate: Stage
    publish: Stage


@dataclass
class ProductionContext:
    run_id: str
    snapshot_id: str
    mode: str
    source_commit: str
    started_at: str
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    manifest_hash: str | None = None
    artifact_path: str | None = None

    @property
    def deep(self) -> bool:
        return self.mode == "weekly"


@dataclass(frozen=True)
class ProductionResult:
    run_id: str
    snapshot_id: str
    status: str
    failure_stage: str | None = None
    failure_reason: str | None = None
    published_commit: str | None = None


class StageFailure(RuntimeError):
    pass


class ProductionOrchestrator:
    STAGES = (
        "refresh", "score", "select_top", "evaluate_theses", "monitor", "build_site",
    )

    def __init__(self, conn: sqlite3.Connection, stages: ProductionStages, *,
                 source_commit: str, now: Callable[[], str]):
        self.conn = conn
        self.stages = stages
        self.source_commit = source_commit
        self.now = now

    def _record_domain_results(self, context: ProductionContext) -> None:
        for member in context.results["select_top"].get("members", []):
            db.append_production_top_member(self.conn, {
                "run_id": context.run_id,
                "security_key": member["security_key"], "symbol": member["symbol"],
                "rank": member["rank"], "score": member["score"],
            })
        for evaluation in context.results["evaluate_theses"].get("evaluations", []):
            db.append_production_thesis_evaluation(self.conn, {
                "run_id": context.run_id,
                "security_key": evaluation["security_key"],
                "symbol": evaluation["symbol"],
                "input_fingerprint": evaluation["input_fingerprint"],
                "outcome": evaluation["outcome"],
                "evaluated_at": evaluation["evaluated_at"],
                "reason_code": evaluation["reason_code"],
                "thesis_version": evaluation.get("thesis_version"),
            })
        self.conn.commit()

    def run(self, *, mode: str, run_id: str | None = None,
            snapshot_id: str | None = None) -> ProductionResult:
        if mode not in {"daily", "weekly", "manual"}:
            raise ValueError(f"invalid production mode {mode!r}")
        run_id = run_id or f"run-{uuid.uuid4().hex}"
        snapshot_id = snapshot_id or f"snap-{uuid.uuid4().hex}"
        context = ProductionContext(
            run_id=run_id, snapshot_id=snapshot_id, mode=mode,
            source_commit=self.source_commit, started_at=self.now(),
        )
        state.start_run(
            self.conn, run_id=run_id, mode=mode, source_commit=self.source_commit,
            started_at=context.started_at,
        )
        current = "start"
        try:
            for current in self.STAGES:
                context.results[current] = getattr(self.stages, current)(context) or {}
            self._record_domain_results(context)
            build = context.results["build_site"]
            context.manifest_hash = str(build["manifest_hash"])
            context.artifact_path = str(build["artifact_path"])

            current = "validate"
            validation = self.stages.validate(context) or {}
            context.results[current] = validation
            if not validation.get("passed"):
                raise StageFailure(
                    "release gates failed: " + ", ".join(validation.get("failed") or [])
                )
            state.validate_run(self.conn, run_id, finished_at=self.now())
            state.stage_snapshot(
                self.conn, snapshot_id=snapshot_id, run_id=run_id,
                manifest_hash=context.manifest_hash,
                artifact_path=Path(context.artifact_path), created_at=self.now(),
            )

            current = "promote"
            state.promote_snapshot(self.conn, snapshot_id)

            current = "publish"
            published = self.stages.publish(context) or {}
            commit = str(published["commit"])
            state.record_published_commit(
                self.conn, snapshot_id, commit, finished_at=self.now())
            return ProductionResult(run_id, snapshot_id, "PUBLISHED",
                                    published_commit=commit)
        except Exception as error:  # one boundary records the exact failed stage
            reason = f"{type(error).__name__}: {error}"
            if current == "publish":
                state.record_publication_failure(
                    self.conn, run_id, reason=reason, finished_at=self.now())
                return ProductionResult(run_id, snapshot_id, "VALIDATED", current, reason)
            state.fail_run(
                self.conn, run_id, stage=current, reason=reason, finished_at=self.now())
            return ProductionResult(run_id, snapshot_id, "FAILED", current, reason)

    def retry_publish(self, run_id: str) -> ProductionResult:
        row = self.conn.execute(
            "SELECT pr.source_commit, ps.* FROM production_run pr"
            " JOIN production_snapshot ps USING(run_id) WHERE pr.run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown staged production run {run_id}")
        context = ProductionContext(
            run_id=run_id, snapshot_id=row["snapshot_id"], mode="manual",
            source_commit=row["source_commit"], started_at=self.now(),
            manifest_hash=row["manifest_hash"], artifact_path=row["artifact_path"],
        )
        try:
            published = self.stages.publish(context) or {}
            commit = str(published["commit"])
            state.record_published_commit(
                self.conn, row["snapshot_id"], commit, finished_at=self.now())
            return ProductionResult(run_id, row["snapshot_id"], "PUBLISHED",
                                    published_commit=commit)
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            state.record_publication_failure(
                self.conn, run_id, reason=reason, finished_at=self.now())
            return ProductionResult(run_id, row["snapshot_id"], "VALIDATED",
                                    "publish", reason)


def _git_commit(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        text=True, capture_output=True,
    ).stdout.strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "retry-publish", "status"):
        command = sub.add_parser(name)
        command.add_argument("--state-dir", required=True)
        if name == "run":
            command.add_argument("--mode", choices=("daily", "weekly", "manual"),
                                 required=True)
        else:
            command.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    conn = db.open_db(Path(args.state_dir))
    db.migrate(conn)
    if args.command == "status":
        row = conn.execute(
            "SELECT * FROM production_run WHERE run_id=?", (args.run_id,)
        ).fetchone()
        print(json.dumps(dict(row) if row else {"error": "unknown run"}, sort_keys=True))
        return 0 if row else 2
    print("production CLI requires configured stage adapters; use deploy/local wrapper")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
