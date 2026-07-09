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


def _seed_thesis(conn):
    # minimal thesis + two versions via the append helpers (journal-FK first)
    je = db.append_journal_entry(conn, {"ts": "2026-01-01T00:00:00Z",
        "decision_type": "gate_verdict", "actor": "owner"})
    db.append_thesis(conn, thesis_id="TH-DDOG-001", ticker="DDOG", origin="gate",
                     created_at="2026-01-01T00:00:00Z")
    base = {"thesis_id": "TH-DDOG-001", "business_model_2s": "Observability SaaS.",
            "moat_types_json": '["switching_costs"]', "moat_evidence": "workflow lock-in",
            "owner_earnings_json": "{}", "owner_earnings_narrative": "FCF growing",
            "value_at_purchase": None, "fair_band_low": 28.0, "fair_band_high": 36.0,
            "denominator_note": None, "conviction": "high", "mgmt_trust": "trusted_professional",
            "mgmt_trust_note": None, "circle_fit": "core", "circle_fit_note": None,
            "time_horizon": "10y_plus", "ten_year_statement": "Observability compounds.",
            "status_buy_flag": 0, "status_buy_note": None, "reason": None, "actor": "owner",
            "journal_ref": je, "created_at": "2026-01-01T00:00:00Z"}
    db.append_thesis_version(conn, {**base, "version": 1, "diff_json": None})
    db.append_thesis_version(conn, {**base, "version": 2, "diff_json": '{"fair_band_high":[34,36]}',
                                    "reason": "re-anchored at anniversary"})
    db.append_thesis_status(conn, thesis_id="TH-DDOG-001", status="intact",
                            changed_at="2026-01-01T00:00:00Z", cause="activated")
    return je


def test_write_thesis_view_has_current_fields_and_version_log(tmp_db, tmp_path):
    _seed_thesis(tmp_db)
    p = archive.write_thesis_view(tmp_db, "TH-DDOG-001", archive_dir=tmp_path)
    assert p == tmp_path / "theses" / "TH-DDOG-001.md"
    text = p.read_text(encoding="utf-8")
    assert "TH-DDOG-001" in text and "DDOG" in text
    assert "Observability compounds." in text          # current ten-year statement
    assert "v1" in text and "v2" in text                # version log
    assert "re-anchored at anniversary" in text
    # cost basis is NOT in a thesis view (value_at_purchase is NULL here anyway)
    assert "avg_open_price" not in text


def test_write_journal_entry_with_grade(tmp_db, tmp_path):
    je = _seed_thesis(tmp_db)
    db.append_journal_grade(tmp_db, entry_id=je, graded_at="2026-04-01T00:00:00Z",
                            outcome_grade="good", note="thesis held")
    p = archive.write_journal_entry(tmp_db, je, archive_dir=tmp_path)
    assert p.parent.name == "2026" and p.parent.parent.name == "journal"
    text = p.read_text(encoding="utf-8")
    assert f"JE-{je:04d}" in text or f"JE-{je}" in text
    assert "good" in text and "thesis held" in text     # grade appended as a dated section


def test_rebuild_regenerates_reports_theses_and_journal(tmp_db, tmp_path, monkeypatch):
    from agentcy import gitio
    arch = tmp_path / "archive"
    gitio.ensure_repo(arch)
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    # one report, one thesis, one journal entry
    rh = runlog.start(tmp_db, "daily", "2026-07-08", clock=CLK)
    archive.archive_and_store(tmp_db, RenderedOutput("x", "# Daily\n\nbody", "daily"),
        run_id=rh.run_id, report_type="daily", period="2026-07-08",
        freshness={}, clock=CLK, archive_dir=arch)
    je = _seed_thesis(tmp_db)
    # wipe the working tree (simulate archive corruption) then rebuild from the DB
    for sub in ("letters", "theses", "journal"):
        d = arch / sub
        if d.exists():
            shutil.rmtree(d)
    n = archive.rebuild(tmp_db, archive_dir=arch)
    assert n >= 3                                       # >=1 report + 1 thesis + 1 journal
    assert (arch / "letters" / "2026-07-08.md").read_text(encoding="utf-8").startswith("# Daily")
    assert (arch / "theses" / "TH-DDOG-001.md").exists()
    assert list((arch / "journal").rglob("JE-*.md"))    # at least one journal file
