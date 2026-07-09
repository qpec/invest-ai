import shutil
import pytest
from pathlib import Path
from datetime import datetime, timezone
from agentcy import archive, db, runlog
from agentcy.clock import FixedClock
from agentcy.render.contexts import RenderedOutput

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")
CLK = FixedClock(datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc))


def test_path_for_layout(tmp_path):
    p = archive.path_for("daily", "2026-07-08", archive_dir=tmp_path)
    assert p == tmp_path / "letters" / "2026-07-08.md"
    assert archive.path_for("weekly", "2026-07-11", archive_dir=tmp_path).parent.name == "weekly"
    assert archive.path_for("quarterly", "Q2-2026", archive_dir=tmp_path).parent.name == "quarterly"
    assert archive.path_for("alert", "A238", archive_dir=tmp_path).parent.name == "alerts"
    assert archive.path_for("event", "MSFT-2026-07-08", archive_dir=tmp_path).parent.name == "events"
    assert archive.path_for("gate", "ASML", archive_dir=tmp_path).parent.name == "gate"


def test_archive_and_store_writes_file_commits_and_rows(tmp_db, tmp_path, monkeypatch):
    from agentcy import gitio
    arch = tmp_path / "archive"
    gitio.ensure_repo(arch)
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    # a run to reference
    rh = runlog.start(tmp_db, "daily", "2026-07-08", clock=CLK)
    r = RenderedOutput(telegram_html="<b>x</b>", markdown="# Daily letter\n\nbody",
                       output_class="daily")
    rid = archive.archive_and_store(tmp_db, r, run_id=rh.run_id, report_type="daily",
                                    period="2026-07-08", freshness={"prices": "fresh"},
                                    clock=CLK, archive_dir=arch)
    row = db.fetch_report(tmp_db, rid)
    assert row["type"] == "daily" and row["period"] == "2026-07-08"
    assert row["git_sha"] and len(row["git_sha"]) == 40
    assert (arch / "letters" / "2026-07-08.md").read_text(encoding="utf-8").startswith("# Daily letter")
    assert row["archive_path"].endswith("letters/2026-07-08.md")


def test_archive_and_store_git_sha_null_when_commit_fails(tmp_db, tmp_path, monkeypatch):
    arch = tmp_path / "nope"           # NOT a git repo -> commit returns None
    arch.mkdir()
    rh = runlog.start(tmp_db, "daily", "2026-07-09", clock=CLK)
    r = RenderedOutput(telegram_html="x", markdown="body", output_class="daily")
    rid = archive.archive_and_store(tmp_db, r, run_id=rh.run_id, report_type="daily",
                                    period="2026-07-09", freshness={}, clock=CLK, archive_dir=arch)
    row = db.fetch_report(tmp_db, rid)
    assert row["git_sha"] is None      # write-once NULL; the report row still lands
    assert (arch / "letters" / "2026-07-09.md").exists()   # file written regardless
