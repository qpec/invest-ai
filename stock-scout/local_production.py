"""Concrete local adapters for the production orchestrator."""
from __future__ import annotations

import hashlib
import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import monitor
import thesis
import webapp
from agentcy import market_prices
from agentcy import production as release


@dataclass(frozen=True)
class LocalProductionConfig:
    artifact_root: Path
    sec_data: Path
    price_grid: Path
    universe: Path
    enrich_cache: Path
    theses_dir: Path
    reports_dir: Path
    as_of: str
    network_refresh: bool = False


def export_price_grid(conn: sqlite3.Connection, directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    count = 0
    for row in conn.execute(
        "SELECT provider_symbol, bar_date, raw_close, adjusted_close, split_ratio,"
        " provider FROM v_current_market_price ORDER BY provider_symbol"
    ):
        payload = {
            "symbol": row["provider_symbol"],
            "bars": {row["bar_date"]: {
                "close": float(row["raw_close"]),
                "adj_close": float(row["adjusted_close"]),
            }},
            "splits": ({row["bar_date"]: float(row["split_ratio"])}
                       if row["split_ratio"] else {}),
            "source": row["provider"],
            "price_basis": "raw",
        }
        target = directory / f"{row['provider_symbol']}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(target)
        count += 1
    return count


def write_eligible_universe(conn: sqlite3.Connection, source: Path,
                            target: Path) -> int:
    """Project the configured universe onto the current security-master allowlist."""
    eligible = {
        str(row["symbol"]) for row in conn.execute(
            "SELECT DISTINCT symbol FROM v_eligible_security")
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with source.open(newline="", encoding="utf-8-sig") as handle, temporary.open(
        "w", newline="", encoding="utf-8"
    ) as output:
        reader = csv.DictReader(handle)
        writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
        writer.writeheader()
        count = 0
        for row in reader:
            if row.get("symbol") in eligible:
                writer.writerow(row)
                count += 1
    temporary.replace(target)
    return count


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_local_stages(conn: sqlite3.Connection, config: LocalProductionConfig,
                      *, publish=lambda context: {"commit": "STAGED"}):
    from production import ProductionStages

    def refresh(context):
        if config.network_refresh:
            now = datetime.now(timezone.utc)
            summary = market_prices.refresh(
                conn, state_dir=config.artifact_root, now=now, scheduled_for=config.as_of,
                budget=int(conn.execute(
                    "SELECT COUNT(*) FROM v_eligible_security").fetchone()[0]),
            )
            if summary.status != "SUCCEEDED":
                raise RuntimeError(f"price refresh ended {summary.status}")
            import enrich
            symbols = enrich.universe_symbols_csv(config.universe)
            priority = enrich.thesis_symbols(config.theses_dir)
            refreshed = enrich.rolling_refresh(
                config.enrich_cache, symbols, priority=priority,
                budget=len(symbols) if context.deep else 1500,
            )
        else:
            refreshed = {"network": "skipped"}
        price_count = export_price_grid(conn, config.price_grid)
        if not price_count:
            raise RuntimeError("no promoted market prices available")
        return {"prices": price_count, "filings": refreshed}

    def score(context):
        eligible_universe = (
            config.artifact_root / context.run_id / "eligible-universe.csv"
        )
        eligible_count = write_eligible_universe(
            conn, config.universe, eligible_universe)
        if not eligible_count:
            raise RuntimeError("security master has no eligible universe rows")
        model = webapp.assemble(
            sec_data=str(config.sec_data), prices_dir=str(config.price_grid),
            universe=str(eligible_universe), as_of=config.as_of,
            enrich_cache=str(config.enrich_cache), theses_dir=str(config.theses_dir),
            log=lambda message: None,
        )
        model["snapshot_id"] = context.snapshot_id
        context.runtime["model"] = model
        return {"eligible": model["counts"]["screened"], "rows": model["rows"]}

    def select_top(context):
        model = context.runtime["model"]
        details = model.get("details") or {}
        members = []
        for item in model["thesis"]["top"]:
            symbol = item["sym"]
            card = (details.get(symbol) or {}).get("card") or {}
            members.append({
                "security_key": symbol, "symbol": symbol, "rank": int(item["rank"]),
                "score": float(card.get("score") or item.get("pct") or 0.0),
            })
        return {"members": members}

    def evaluate_theses(context):
        model = context.runtime["model"]
        by_symbol = {row["s"]: row for row in model["rows"]}
        evaluations = []
        for member in context.results["select_top"]["members"]:
            symbol = member["symbol"]
            compact = by_symbol[symbol]
            row = {
                "security_key": member["security_key"], "symbol": symbol,
                "rank": member["rank"],
                "card": {"score": member["score"], "pct": compact.get("pct"),
                         "band": compact.get("band"), "evidence": compact.get("ev")},
                "bundle": {"metric_evidence_ids": []},
            }
            fingerprint = thesis.research_fingerprint(row, "scout-v1")
            previous = conn.execute(
                "SELECT input_fingerprint FROM production_thesis_evaluation"
                " WHERE security_key=? AND outcome!='FAILED'"
                " ORDER BY evaluated_at DESC, run_id DESC LIMIT 1",
                (member["security_key"],),
            ).fetchone()
            record = config.theses_dir / "drafts" / symbol / "record.json"
            stale = context.deep and record.exists()
            outcome, reason = thesis.evaluation_decision(
                previous["input_fingerprint"] if previous else None, fingerprint, stale)
            evaluations.append({
                **member, "input_fingerprint": fingerprint, "outcome": outcome,
                "evaluated_at": context.started_at, "reason_code": reason,
                "thesis_version": None,
            })
        return {"evaluations": evaluations}

    def run_monitor(context):
        rc = monitor.main([
            "run", "--sec-data", str(config.sec_data), "--prices", str(config.price_grid),
            "--universe", str(config.universe), "--as-of", config.as_of,
            "--theses-dir", str(config.theses_dir), "--reports-dir", str(config.reports_dir),
            "--enrich-cache", str(config.enrich_cache),
        ])
        if rc:
            raise RuntimeError(f"monitor exited {rc}")
        committed, monitored = [], []
        for path in sorted((config.theses_dir / "committed").glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            committed.append(doc["symbol"])
            if doc.get("last_monitored") == config.as_of:
                monitored.append(doc["symbol"])
        return {"committed": committed, "monitored": monitored}

    def build_site(context):
        artifact = config.artifact_root / context.run_id
        docs = artifact / "docs"
        model = context.runtime["model"]
        webapp.write_site(model, docs)
        manifest = {
            "schema_version": 1, "run_id": context.run_id,
            "snapshot_id": context.snapshot_id, "as_of": config.as_of,
            "source_commit": context.source_commit,
            "counts": model["counts"],
        }
        manifest_path = artifact / "production-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        return {
            "artifact_path": str(artifact), "manifest_hash": _file_hash(manifest_path),
            "component_snapshot_ids": [context.snapshot_id], "public_model": model,
        }

    def validate(context):
        score_result = context.results["score"]
        monitor_result = context.results["monitor"]
        build = context.results["build_site"]
        outcome = release.validate_release(release.ReleaseInput(
            snapshot_id=context.snapshot_id, eligible=int(score_result["eligible"]),
            top_members=len(context.results["select_top"]["members"]),
            committed_symbols=frozenset(monitor_result["committed"]),
            monitored_symbols=frozenset(monitor_result["monitored"]),
            component_snapshot_ids=frozenset(build["component_snapshot_ids"]),
            public_model=build["public_model"],
            index_exists=(Path(build["artifact_path"]) / "docs" / "index.html").exists(),
            manifest_exists=(Path(build["artifact_path"]) /
                             "production-manifest.json").exists(),
            data_quality_passed=True,
        ))
        return {"passed": outcome.passed, "failed": list(outcome.failed),
                "checks": outcome.checks}

    return ProductionStages(
        refresh=refresh, score=score, select_top=select_top,
        evaluate_theses=evaluate_theses, monitor=run_monitor, build_site=build_site,
        validate=validate, publish=publish,
    )
