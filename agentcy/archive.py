"""Archive layer: rendered markdown -> archive-repo file -> gitio.commit (non-fatal) ->
report row. The archive is DERIVED data (§8) — rebuild() regenerates it from the DB, so
archive corruption is never data loss. Writes go through db.append_report; the git commit
precedes the insert so git_sha is write-once at insert (contract §2.1)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from agentcy import db, gitio
from agentcy.clock import Clock
from agentcy.render.contexts import RenderedOutput

_SUBDIR = {"daily": "letters", "weekly": "weekly", "quarterly": "quarterly",
           "alert": "alerts", "event": "events", "gate": "gate"}


def _archive_dir(archive_dir: Path | None) -> Path:
    if archive_dir is not None:
        return archive_dir
    return db.state_dir() / "archive"


def path_for(report_type: str, period: str, *, archive_dir: Path) -> Path:
    """letters|weekly|quarterly|alerts|events|gate/<period>.md (§8). The DB keeps the
    period verbatim; the on-disk filename maps ':' (event key '{ticker}:{detected_at}')
    to '-' so the git-tracked archive stays portable off Linux. Deterministic, so
    archive_and_store and rebuild agree on the same file."""
    safe = period.replace(":", "-")
    return archive_dir / _SUBDIR[report_type] / f"{safe}.md"


def archive_and_store(conn, r: RenderedOutput, *, run_id: int, report_type: str, period: str,
                      freshness: Mapping, clock: Clock, archive_dir: Path | None = None) -> int:
    """Write markdown into the archive repo -> commit (non-fatal; None -> git_sha NULL +
    a data-health line the caller logs) -> append report row; returns report_id.
    Commit precedes the insert so git_sha is write-once at insert (contract §2.1)."""
    arch = _archive_dir(archive_dir)
    path = path_for(report_type, period, archive_dir=arch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(r.markdown, encoding="utf-8", newline="\n")

    sha = gitio.commit(arch, [path], f"{report_type}: {period}")

    return db.append_report(conn, {
        "run_id": run_id,
        "type": report_type,
        "generated_at": db.to_iso(clock.now()),
        "period": period,
        "freshness_json": json.dumps(freshness, sort_keys=True),
        "content_md": r.markdown,
        "archive_path": str(path).replace("\\", "/"),
        "git_sha": sha,
    })


def write_thesis_view(conn, thesis_id: str, *, archive_dir: Path | None = None) -> Path:
    """Regenerate theses/TH-XXXX-NNN.md: current fields + full version log (R10). No
    cost basis (value_at_purchase) in a thesis view — quarantine by absence."""
    arch = _archive_dir(archive_dir)
    th = db.fetch_thesis(conn, thesis_id)
    cur = db.fetch_current_thesis_version(conn, thesis_id)
    st = db.fetch_current_thesis_status(conn, thesis_id)
    lines = [f"# {thesis_id} — {th['ticker']}", "",
             f"Status: {st['status'] if st else 'draft'} · conviction: {cur['conviction']} · "
             f"circle: {cur['circle_fit']}", "",
             "## Business model", cur["business_model_2s"], "",
             "## Moat", cur["moat_evidence"], "",
             "## Ten-year statement", cur["ten_year_statement"], "",
             f"## Fair band (v{cur['version']})", f"{cur['fair_band_low']:g}–{cur['fair_band_high']:g}×", "",
             "## Version log"]
    for v in db.fetch_thesis_versions(conn, thesis_id):
        line = f"- v{v['version']} ({v['created_at']})"
        if v["reason"]:
            line += f" — {v['reason']}"
        if v["diff_json"]:
            line += f" · diff: {v['diff_json']}"
        lines.append(line)
    path = arch / "theses" / f"{thesis_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def write_journal_entry(conn, entry_id: int, *, archive_dir: Path | None = None) -> Path:
    """journal/YYYY/JE-NNNN.md — immutable entry; grades appended as dated sections."""
    arch = _archive_dir(archive_dir)
    e = db.fetch_journal_entry(conn, entry_id)
    year = e["ts"][:4]
    lines = [f"# JE-{entry_id:04d} — {e['decision_type']}"
             + (f" / {e['decision_subtype']}" if e["decision_subtype"] else ""), "",
             f"Timestamp: {e['ts']} · actor: {e['actor']}"]
    if e["ticker"]:
        lines.append(f"Ticker: {e['ticker']}")
    if e["reasoning_at_the_moment"]:
        lines += ["", "## Reasoning at the moment", e["reasoning_at_the_moment"]]
    if e["system_recommendation"]:
        lines += ["", "## System recommendation (verbatim)", e["system_recommendation"]]
    for g in db.fetch_grades_for(conn, entry_id):
        lines += ["", f"## Grade — {g['graded_at']}: {g['outcome_grade']}"]
        if g["note"]:
            lines.append(g["note"])
    path = arch / "journal" / year / f"JE-{entry_id:04d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def rebuild(conn, *, archive_dir: Path | None = None) -> int:
    """agentcy render --rebuild: regenerate EVERY archive file from the DB — archive
    corruption is never data loss (§8). Reports come from the stored content_md; thesis
    views and journal entries are re-rendered. Returns the count of files written.
    Enumeration goes through the contracted readers (db.fetch_theses / db.fetch_journal_entries,
    R10), never inline SELECTs."""
    arch = _archive_dir(archive_dir)
    n = 0

    for rep in db.fetch_reports(conn):
        try:
            path = path_for(rep["type"], rep["period"], archive_dir=arch)
        except KeyError:
            continue   # unknown type (shouldn't happen; CHECK-constrained) -> skip, never crash rebuild
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rep["content_md"], encoding="utf-8", newline="\n")
        n += 1

    for th in db.fetch_theses(conn):
        write_thesis_view(conn, th["thesis_id"], archive_dir=arch)
        n += 1

    for e in db.fetch_journal_entries(conn):
        write_journal_entry(conn, e["entry_id"], archive_dir=arch)
        n += 1

    return n
