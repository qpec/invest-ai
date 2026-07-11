"""Stage-2 review-artifact round-trip: append-only table + latest-per-(ticker,axis) view
(design 2026-07-11 Part A). NOT monitoring state."""
import pytest
from agentcy import db


def test_migration_003_applied_and_append_only(tmp_db):
    # the table + view + guards exist after migrate()
    tables = {r["name"] for r in tmp_db.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}
    assert "scout_shortlist_verdict" in tables
    assert "v_scout_shortlist_verdict" in tables
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="moat", value="confirmed",
                            reason="switching costs", recorded_at="2026-07-11T10:00:00Z")
    # append-only: UPDATE and DELETE both abort (invariant 1)
    with pytest.raises(Exception):
        tmp_db.execute("UPDATE scout_shortlist_verdict SET value='not-evident'")
    with pytest.raises(Exception):
        tmp_db.execute("DELETE FROM scout_shortlist_verdict")


def test_latest_wins_per_ticker_axis(tmp_db):
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="moat", value="not-evident",
                            reason="first pass", recorded_at="2026-07-11T10:00:00Z")
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="moat", value="confirmed",
                            reason="revised", recorded_at="2026-07-11T11:00:00Z")
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="fad", value="clear",
                            reason=None, recorded_at="2026-07-11T11:00:00Z")
    rows = {r["axis"]: r for r in db.fetch_scout_verdicts_current(tmp_db, "MSFT")}
    assert rows["moat"]["value"] == "confirmed"       # latest supersedes
    assert rows["moat"]["reason"] == "revised"
    assert rows["fad"]["value"] == "clear"
    # a pending axis (mgmt/tier never recorded) is simply absent, never faked
    assert set(rows) == {"moat", "fad"}
