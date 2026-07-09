"""build_status_context (R2) — /status glue that reports last RunLog state, never runs checks.
Reads mirror.balance + asks.open_asks + runlog, produces a StatusContext (no benchmark/euro)."""
from __future__ import annotations

from agentcy import asks, mirror, runlog
from agentcy.render.contexts import StatusContext
from agentcy.render.daily import build_status_context, render_status
from agentcy.render.lint import lint


def _pos(symbol, mv):
    return mirror.PositionIn(symbol=symbol, yf_ticker=symbol, instrument_type="stock",
                             quantity=1.0, avg_open_price=None, native_currency="USD",
                             mv_native=mv, mv_eur=mv, weight=0.0, leverage=1.0)


def _snap(cash, positions, as_of="2026-07-06"):
    return mirror.SnapshotIn(as_of=as_of, source="manual_export", cash_balance_eur=cash,
                             positions=tuple(positions))


def test_build_status_context_reports_last_run_state(tmp_db, fixed_clock, golden):
    mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("VEEV", 2300), _pos("CRWD", 1472)]),
                           clock=fixed_clock)
    h = runlog.start(tmp_db, "daily", "2026-07-08", clock=fixed_clock)
    runlog.finish(tmp_db, h.run_id, status="ok", outputs={"letter": 1}, clock=fixed_clock)

    ctx = build_status_context(tmp_db, as_of=fixed_clock.now())
    assert isinstance(ctx, StatusContext)
    # header comes straight from mirror.balance — no euro amounts, only band-%
    assert ctx.header.n_framework + ctx.header.n_backfill + ctx.header.n_outside == 2
    assert ctx.header.cash_band_low == 5.0 and ctx.header.cash_band_high == 15.0
    # calm: no open decisions -> no open loops, verdict is the all-clear line
    assert ctx.open_loops == () and "intact" in ctx.verdict_line
    # next-scheduled sentence is the canonical spec wording, not a computed date (R2)
    assert ctx.next_scheduled_line == "Next scheduled: daily letter after tonight's US close."
    # renders clean through the pure /status renderer
    r = render_status(ctx)
    assert r.output_class == "status" and r.ask_id is None and lint(r) == []
    assert "€" not in r.telegram_html and "S&P" not in r.telegram_html
    # pin the real daemon path (build_status_context -> render_status), not just the fixture
    golden("status_card_builder.html.txt", r.telegram_html)
    golden("status_card_builder.md.txt", r.markdown)


def test_build_status_context_surfaces_open_decision_as_loop(tmp_db, fixed_clock, golden):
    mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("CRWD", 1472)]), clock=fixed_clock)
    ask = asks.mint(tmp_db, kind="A", prompt="CRWD alert — decide", options=("confirm", "refute"),
                    thesis_ref="CRWD", clock=fixed_clock)

    ctx = build_status_context(tmp_db, as_of=fixed_clock.now())
    assert [ol.ask_id for ol in ctx.open_loops] == [ask.ask_id]
    # label carries no ask_id — the renderer supplies the tappable [ask_id] once
    assert ctx.open_loops[0].label == "alert decision open"
    r = render_status(ctx)
    assert r.ask_id == ask.ask_id and ask.ask_id in r.telegram_html
    # ask_id appears exactly once (no doubled suffix) on the open-loop line
    assert r.telegram_html.count(ask.ask_id) == 1
    # pin the daemon path with an open loop present (previously only the calm card had a golden)
    golden("status_card_open_loop.html.txt", r.telegram_html)
    golden("status_card_open_loop.md.txt", r.markdown)


def test_build_status_context_never_writes_run_log(tmp_db, fixed_clock):
    mirror.ingest_snapshot(tmp_db, _snap(300.0, [_pos("VEEV", 2300)]), clock=fixed_clock)
    before = tmp_db.execute("SELECT COUNT(*) FROM run_log").fetchone()[0]
    build_status_context(tmp_db, as_of=fixed_clock.now())
    after = tmp_db.execute("SELECT COUNT(*) FROM run_log").fetchone()[0]
    assert before == after == 0   # reports state, executes nothing (§1.2)
