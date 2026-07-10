"""universe_fetch progress log + v_universe_fetch view (populator design 4).
Append-only, trigger-guarded, latest-per-ticker view - the price_cache/v_price idiom."""
import pytest


def _append(conn, ticker, outcome, at, run_id=None):
    from agentcy import db
    return db.append_universe_fetch(conn, yf_ticker=ticker, outcome=outcome,
                                    attempted_at=at, run_id=run_id)


def test_append_and_view_returns_latest_per_ticker(tmp_db):
    from agentcy import db
    _append(tmp_db, "AAA", "failed", "2026-07-01T00:00:00Z")
    _append(tmp_db, "AAA", "ok", "2026-07-02T00:00:00Z")  # newer wins in the view
    _append(tmp_db, "BBB", "no_data", "2026-07-01T00:00:00Z")
    latest = db.fetch_universe_fetch_latest(tmp_db)
    assert latest["AAA"]["outcome"] == "ok"
    assert latest["AAA"]["last_attempt"] == "2026-07-02T00:00:00Z"
    assert latest["BBB"]["outcome"] == "no_data"


def test_failure_count_since_last_ok(tmp_db):
    from agentcy import db
    _append(tmp_db, "AAA", "failed", "2026-07-01T00:00:00Z")
    _append(tmp_db, "AAA", "no_data", "2026-07-02T00:00:00Z")
    _append(tmp_db, "AAA", "ok", "2026-07-03T00:00:00Z")  # resets the streak
    _append(tmp_db, "AAA", "failed", "2026-07-04T00:00:00Z")
    _append(tmp_db, "AAA", "rate_limited", "2026-07-05T00:00:00Z")  # not a dead-list failure
    counts = db.fetch_universe_fetch_failure_counts(tmp_db)
    # only 'failed'/'no_data' after the last 'ok' count toward the dead list (design 6)
    assert counts["AAA"] == 1


def test_table_is_append_only(tmp_db):
    _append(tmp_db, "AAA", "ok", "2026-07-01T00:00:00Z")
    with pytest.raises(Exception):
        tmp_db.execute("UPDATE universe_fetch SET outcome='failed'")
    with pytest.raises(Exception):
        tmp_db.execute("DELETE FROM universe_fetch")


def test_unknown_outcome_rejected_by_check(tmp_db):
    with pytest.raises(Exception):
        _append(tmp_db, "AAA", "bogus", "2026-07-01T00:00:00Z")


def test_populate_is_an_accepted_run_type(tmp_db, fixed_clock):
    """M3: migration 002 re-creates the run_log.run_type CHECK to admit 'populate'
    (and preserves every prior run_type + the identity column guard)."""
    from agentcy import runlog
    # 'populate' now logs under its own run_type via the real write path.
    handle = runlog.start(tmp_db, "populate", "2026-07-11", clock=fixed_clock)
    row = tmp_db.execute("SELECT run_type FROM run_log WHERE run_id=?",
                         (handle.run_id,)).fetchone()
    assert row["run_type"] == "populate"
    # a prior run_type still passes the re-created CHECK.
    runlog.start(tmp_db, "scout", "2026-07-11", clock=fixed_clock)
    # an unknown run_type is still rejected by the re-created CHECK.
    with pytest.raises(Exception):
        tmp_db.execute(
            "INSERT INTO run_log (run_type, scheduled_for, created_at, started_at)"
            " VALUES ('bogus', 'x', 'x', 'x')")
    # the identity column guard survived the table rebuild.
    with pytest.raises(Exception):
        tmp_db.execute("UPDATE run_log SET run_type='scout' WHERE run_id=?",
                       (handle.run_id,))
