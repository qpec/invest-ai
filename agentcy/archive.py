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
    """letters|weekly|quarterly|alerts|events|gate/<period>.md (§8)."""
    return archive_dir / _SUBDIR[report_type] / f"{period}.md"


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
