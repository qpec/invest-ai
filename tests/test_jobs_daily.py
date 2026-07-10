"""P6.4: daily job core — D.1 checks, classification, letter assembly + delivery."""
from agentcy import db, runlog


def _patch_refresh(monkeypatch, outcomes):
    from agentcy.jobs import daily
    monkeypatch.setattr(daily, "refresh_prices", lambda conn, tickers, **kw: dict(outcomes))


def test_monitored_tickers_held_plus_fx(seeded_portfolio):
    from agentcy.jobs import daily
    ts = daily.monitored_tickers(seeded_portfolio["conn"])
    assert "MSFT" in ts and "USDEUR=X" in ts


def test_classify_market_day():
    from agentcy.jobs import daily
    assert daily.classify_market_day({"MSFT": "ok", "USDEUR=X": "ok"}) == "open"
    assert daily.classify_market_day({"MSFT": "no_new_bar", "USDEUR=X": "no_new_bar"}) == "holiday"
    assert daily.classify_market_day({"MSFT": "failed", "USDEUR=X": "failed"}) == "outage"
    assert daily.classify_market_day({"A": "failed", "B": "failed", "C": "ok"}) == "degraded"


def _finish_prior_daily_keys(conn, fixed_clock, keep):
    """Steady state: every earlier due day already ran, so today's sweep has exactly one
    on-time key. Without this the 14-day lookback would leave 13 late keys, and the fix to
    P6.4 (late keys build+archive+deliver, no short-circuit) would archive all of them."""
    from agentcy import runlog
    for key in runlog.due_keys("daily", as_of=fixed_clock.now()):
        if key == keep:
            continue
        h = runlog.start(conn, "daily", key, clock=fixed_clock)
        runlog.finish(conn, h.run_id, status="ok", outputs={"kind": "pulse"}, clock=fixed_clock)


def test_run_one_full_letter_archives_and_enqueues(seeded_portfolio, fixed_clock, tmp_path, monkeypatch):
    from agentcy.jobs import daily, runner
    conn = seeded_portfolio["conn"]
    _finish_prior_daily_keys(conn, fixed_clock, keep="2026-07-08")
    _patch_refresh(monkeypatch, {"MSFT": "ok", "USDEUR=X": "ok"})
    rc = runner.sweep_and_run(conn, "daily", daily.run_one, clock=fixed_clock, state_dir=tmp_path)
    assert rc == 0
    run = db.fetch_run(conn, "daily", "2026-07-08")
    assert run["status"] == "ok"
    reports = db.fetch_reports(conn, type="daily")
    assert len(reports) == 1 and reports[0]["period"] == "2026-07-08"
    ob = db.fetch_outbox_by_key(conn, "daily:2026-07-08:letter")
    assert ob is not None and ob["kind"] == "daily" and ob["payload_html"]


def test_late_keys_build_and_archive_letters(seeded_portfolio, fixed_clock, tmp_path, monkeypatch):
    """P6.4 catch-up honesty (§1.3): a backlog of missed days must each archive a real letter
    (delivered-late banner), not be short-circuited — so P6.8's 'earlier letters are in the
    archive' promise holds. Newest key is on-time; all earlier swept keys are late."""
    from agentcy.jobs import daily, runner
    conn = seeded_portfolio["conn"]
    _patch_refresh(monkeypatch, {"MSFT": "ok", "USDEUR=X": "ok"})
    rc = runner.sweep_and_run(conn, "daily", daily.run_one, clock=fixed_clock, state_dir=tmp_path)
    assert rc == 0
    reports = db.fetch_reports(conn, type="daily")
    periods = {r["period"] for r in reports}
    # every due day (on-time 2026-07-08 + the 13 caught-up days) archived its own letter
    assert periods == set(runlog.due_keys("daily", as_of=fixed_clock.now()))
    # each earlier day is queued under its own scheduled key, not the on-time key
    assert db.fetch_outbox_by_key(conn, "daily:2026-07-07:letter") is not None


def test_build_context_header_and_disk_line(seeded_portfolio, fixed_clock, monkeypatch):
    from agentcy.jobs import daily
    conn = seeded_portfolio["conn"]

    class Tiny:  # < 2 GB free
        free = 1 * 1024**3
        total = 100 * 1024**3
        used = 99 * 1024**3
    monkeypatch.setattr(daily.shutil, "disk_usage", lambda p: Tiny())
    ctx = daily.build_daily_context(conn, as_of=fixed_clock.now(), late=False,
                                    market="open", price_outcomes={"MSFT": "ok"})
    assert ctx.kind == "full"
    assert ctx.header is not None and ctx.header.n_framework == 1
    assert ctx.header.cash_band_low == 5.0 and ctx.header.cash_band_high == 15.0
    assert any("below 2 GB" in l for l in ctx.data_lines)          # §11.6 disk tripwire
    assert "No action needed" in ctx.verdict_line or "no action" in ctx.verdict_line.lower()


def test_degraded_and_holiday_classification_in_context(seeded_portfolio, fixed_clock):
    from agentcy.jobs import daily
    conn = seeded_portfolio["conn"]
    ctx = daily.build_daily_context(conn, as_of=fixed_clock.now(), late=False,
                                    market="degraded", price_outcomes={"MSFT": "failed", "X": "ok"})
    assert ctx.kind == "degraded"
    ctx2 = daily.build_daily_context(conn, as_of=fixed_clock.now(), late=False,
                                     market="holiday", price_outcomes={"MSFT": "no_new_bar"})
    assert ctx2.kind == "full"
    assert any("US markets closed" in l for l in ctx2.data_lines)  # holiday != outage (§1.4)
