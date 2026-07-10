"""P6.13: tech-arch §6 weekly housekeeping — 90d raw expiry + cap 10 (RunLog, not journaled),
12-month approval lapse (C.6), 30-day non-execution V ask (§3.10a)."""
from datetime import datetime, timedelta, timezone

from agentcy import db
from agentcy.clock import FixedClock

SAT = FixedClock(datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc))


def _add_item(conn, ticker, stage, *, added_days_ago, stage_days_ago=None, thesis_ref=None):
    added = db.to_iso(SAT.now() - timedelta(days=added_days_ago))
    changed = db.to_iso(SAT.now() - timedelta(days=stage_days_ago if stage_days_ago is not None
                                              else added_days_ago))
    cur = conn.execute(
        "INSERT INTO watchlist_item (ticker, added_at, idea_source, one_line_why, stage,"
        " stage_changed_at, thesis_ref) VALUES (?,?,?,?,?,?,?)",
        (ticker, added, "own_research", "why", stage, changed, thesis_ref))
    return cur.lastrowid


def test_raw_expiry_after_90_days_not_journaled(seeded_portfolio):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _add_item(conn, "OLD", "raw", added_days_ago=95)
    _add_item(conn, "FRESH", "raw", added_days_ago=5)
    n_journal = len(db.fetch_journal_entries(conn))
    out = weekly.housekeeping(conn, run_id=1, clock=SAT)
    stages = {i["ticker"]: i["stage"] for i in db.fetch_watchlist(conn)}
    assert stages["OLD"] == "expired" and stages["FRESH"] == "raw"
    assert "OLD" in out["expired"]
    assert len(db.fetch_journal_entries(conn)) == n_journal      # RunLog, not journaled (C.1)


def test_raw_cap_ten_expires_oldest_overflow(seeded_portfolio):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    for i in range(12):
        _add_item(conn, f"T{i:02d}", "raw", added_days_ago=12 - i)   # T00 oldest
    weekly.housekeeping(conn, run_id=1, clock=SAT)
    raw = [i["ticker"] for i in db.fetch_watchlist(conn, stage="raw")]
    assert len(raw) == 10 and "T00" not in raw and "T01" not in raw


def test_approval_expiry_after_12_months(seeded_portfolio):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _add_item(conn, "STALEWATCH", "gate_approved_waiting", added_days_ago=400, stage_days_ago=380)
    weekly.housekeeping(conn, run_id=1, clock=SAT)
    item = [i for i in db.fetch_watchlist(conn) if i["ticker"] == "STALEWATCH"][0]
    assert item["stage"] == "lapsed"       # lapse also disarms the daily fair-entry check
                                           # (the E.4 scan reads stage='gate_approved_waiting' only)


def test_v_ask_minted_for_30d_unexecuted_buy_ready(seeded_portfolio):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _add_item(conn, "ADBE", "buy_ready_waiting", added_days_ago=45, stage_days_ago=35,
              thesis_ref=None)
    out = weekly.housekeeping(conn, run_id=1, clock=SAT)
    assert len(out["v_asks"]) == 1
    ask = db.fetch_ask(conn, out["v_asks"][0])
    assert ask["kind"] == "V" and "ADBE" in ask["prompt"]
    # idempotent: an open V blocks a duplicate
    assert weekly.housekeeping(conn, run_id=1, clock=SAT)["v_asks"] == []


def test_recent_buy_ready_not_prompted(seeded_portfolio):
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _add_item(conn, "NEW", "buy_ready_waiting", added_days_ago=10)
    assert weekly.housekeeping(conn, run_id=1, clock=SAT)["v_asks"] == []
