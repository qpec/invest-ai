"""Daily job (D.1). Fired by agentcy-daily.timer at 07:00 Europe/Amsterdam, 7 days/week (S0).

Never opens the benchmark store, never reads avg_open_price, never imports quantstats
(invariants 4/7). Reads positions via mirror.advice_positions only.

Catch-up honesty (§1.3): the sweep runs newest-first; every swept key — on-time or late —
assembles, archives and delivers its letter. Late (caught-up) keys carry a delivered-late
banner (build_daily_context(..., late=handle.late) -> late_banner) so the archive holds a
real letter per gap day; the on-time run additionally names the gap (P6.8).
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agentcy import archive, asks, config as config_mod, db, deadman, journal, mirror, register
from agentcy.clock import Clock, SystemClock
from agentcy.journal import EntryIn
from agentcy.fetch import store, yf
from agentcy.fetch.yf import FetchFailed
from agentcy.jobs import runner
from agentcy.render import contexts
from agentcy.render import daily as render_daily_mod
from agentcy.tg import outbox

RUN_TYPE = "daily"
AMS = ZoneInfo("Europe/Amsterdam")
DISK_FLOOR_BYTES = 2 * 1024**3


def main(*, clock: Clock | None = None, state_dir: Path | None = None) -> int:
    clock = clock or SystemClock()
    state_dir = state_dir or db.state_dir()
    conn = db.open_db(state_dir)
    try:
        rc = runner.sweep_and_run(conn, RUN_TYPE, run_one, clock=clock, state_dir=state_dir)
        if rc == 0:
            deadman.ping(conn)                      # S2/R4: one ping per successful daily run
        return rc
    finally:
        conn.close()


def run_one(conn, handle, *, clock: Clock, state_dir: Path) -> tuple[str, dict]:
    as_of = clock.now()
    if is_pulse_day(as_of):                          # Sun/Mon: no preceding US close (§1.4)
        ctx = build_pulse_context(conn, as_of=as_of, late=handle.late)
        _deliver(conn, ctx, handle, clock=clock, state_dir=state_dir)
        return "ok", {"kind": "pulse"}
    outcomes = refresh_prices(conn, monitored_tickers(conn),
                              run_id=handle.run_id, clock=clock, state_dir=state_dir)
    notes = sweep_ask_deadlines(conn, clock=clock, run_id=handle.run_id)   # P6.6
    respooled = respool_lagging_events(conn, as_of=as_of, state_dir=state_dir)  # P6.7
    market = classify_market_day(outcomes)
    ctx = build_daily_context(conn, as_of=as_of, late=handle.late,
                              market=market, price_outcomes=outcomes)
    _deliver(conn, ctx, handle, clock=clock, state_dir=state_dir)
    status = "degraded" if market in ("degraded", "outage") else "ok"
    return status, {"market": market, "price_outcomes": outcomes,
                    "deadline_notes": notes, "respooled": respooled}


def _deliver(conn, ctx, handle, *, clock: Clock, state_dir: Path) -> None:
    """Render -> archive (always) -> enqueue (unless quiet-mode suppresses, P6.8)."""
    r = render_daily_mod.render_daily(ctx)
    report_id = archive.archive_and_store(
        conn, r, run_id=handle.run_id, report_type="daily",
        period=handle.scheduled_for, freshness={"price_outcomes": "see outputs_json"}, clock=clock)
    if letter_suppressed(conn, as_of=clock.now()):   # P6.8; stub below returns False
        return
    base = outbox.scheduled_key(RUN_TYPE, handle.scheduled_for, "letter")
    runner.enqueue_rendered(conn, r, base_key=base, kind="daily",
                            run_id=handle.run_id, clock=clock, artifact_ref=report_id)


def monitored_tickers(conn) -> list[str]:
    """Held mappable non-cash tickers + WATCH-stage watchlist tickers + FX pairs (D.1 inputs)."""
    tickers: list[str] = []
    currencies: set[str] = set()
    snap = db.fetch_latest_snapshot(conn)
    if snap is not None:
        for p in mirror.advice_positions(conn, snap["snapshot_id"]):
            if p.instrument_type != "cash" and p.yf_ticker:
                tickers.append(p.yf_ticker)
                currencies.add(p.native_currency)
    smap = db.fetch_current_symbol_map(conn)
    for item in db.fetch_watchlist(conn, stage="gate_approved_waiting"):
        tickers.append(smap.get(item["ticker"], item["ticker"]))
    tickers += [f"{c}EUR=X" for c in sorted(currencies) if c != "EUR"]
    seen: dict[str, None] = {}
    for t in tickers:
        seen.setdefault(t, None)
    return list(seen)


def refresh_prices(conn, tickers, *, run_id: int, clock: Clock, state_dir: Path) -> dict[str, str]:
    """Per-ticker outcome: 'ok' (new bar stored) | 'no_new_bar' | 'failed'. Paced by yf (§7.2)."""
    outcomes: dict[str, str] = {}
    fetched_at = db.to_iso(clock.now())
    for t in tickers:
        before = db.fetch_v_price(conn, t)
        newest_before = max((r["bar_date"] for r in before), default=None)
        try:
            frame = yf.fetch_daily_bars(t, state_dir=state_dir)
            store.store_price_bars(conn, t, frame, run_id=run_id, fetched_at=fetched_at)
        except FetchFailed:
            outcomes[t] = "failed"
            continue
        after = db.fetch_v_price(conn, t)
        newest_after = max((r["bar_date"] for r in after), default=None)
        outcomes[t] = "ok" if (newest_before is None or (newest_after or "") > newest_before) else "no_new_bar"
    return outcomes


def classify_market_day(outcomes: dict[str, str]) -> str:
    """Empirical, never calendrical (§1.4): holiday and outage are kept strictly apart."""
    if not outcomes:
        return "open"
    n = len(outcomes)
    failed = sum(1 for v in outcomes.values() if v == "failed")
    if failed == n:
        return "outage"
    if failed / n > 0.5:
        return "degraded"                             # >50% stale -> checks 1-2 suspended (D.1)
    if all(v == "no_new_bar" for v in outcomes.values()):
        return "holiday"                              # fetch succeeded, no new bar
    return "open"


def build_daily_context(conn, *, as_of: datetime, late: bool, market: str,
                        price_outcomes: dict[str, str]) -> contexts.DailyContext:
    header = _header(conn, as_of=as_of)
    kind = {"outage": "total_failure", "degraded": "degraded"}.get(market, "full")
    opportunities, more = (opportunity_lines(conn, as_of=as_of)     # P6.5; stub returns ((), 0)
                           if kind == "full" else ((), 0))
    loops = open_loop_lines(conn, as_of=as_of)                      # P6.6; stub returns ()
    data = data_health_lines(conn, as_of=as_of, market=market, price_outcomes=price_outcomes)
    return contexts.DailyContext(
        kind=kind, as_of=as_of, header=None if kind == "total_failure" else header,
        verdict_line=compose_verdict(conn, kind=kind, loops=loops),
        opportunities=opportunities, more_opportunities=more,
        events_line=events_line(conn, as_of=as_of) if kind == "full" else None,  # P6.7; stub None
        data_lines=data, open_loops=loops, open_items_count=len(loops),
        generated_at=as_of, late_banner=_late_banner(as_of) if late else None)


def _header(conn, *, as_of: datetime) -> contexts.HeaderBlock:
    snap = db.fetch_latest_snapshot(conn)
    age = mirror.snapshot_age(conn, as_of=as_of)
    age_days = age.days if age else 0                 # R10: unparseable as_of never crashes the letter
    snap_line = ("no snapshot yet" if snap is None else
                 f"{snap['source'].replace('_', ' ')} of {snap['as_of'][:10]}"
                 f" ({age_days} day{'s' if age_days != 1 else ''} old)")
    bal = mirror.balance(conn, as_of=as_of)
    return contexts.HeaderBlock(
        date_label=_date_label(as_of),
        snapshot_line=snap_line,
        prices_line="fresh (07:00 CET)",
        cash_pct=bal.cash_pct, cash_band_low=config_mod.get_float(conn, "cash_band_low_pct"),
        cash_band_high=config_mod.get_float(conn, "cash_band_high_pct"),
        cash_in_band=bal.cash_in_band,
        n_framework=bal.n_framework, n_backfill=bal.n_backfill, n_outside=bal.n_outside)


def _date_label(as_of: datetime) -> str:
    """Portable '%-d' — strftime('%-d') is POSIX-only; build the day number by hand (plan note)."""
    if not hasattr(as_of, "astimezone"):
        return str(as_of)
    d = as_of.astimezone(AMS)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b %Y')}"


def compose_verdict(conn, *, kind: str, loops) -> str:
    if kind == "degraded":
        return "Checks suspended — market data degraded. Nothing is wrong; I just can't see."
    if loops:
        return f"{len(loops)} open item{'s' if len(loops) != 1 else ''} waiting — see below. No new triggers fired."
    return "No triggers fired. All theses intact. Doing nothing is today's best move. No action needed."


def data_health_lines(conn, *, as_of: datetime, market: str,
                      price_outcomes: dict[str, str]) -> tuple[str, ...]:
    lines: list[str] = []
    if market == "holiday":
        lines.append(f"US markets closed {as_of.astimezone(AMS).date().isoformat()} — no new bar; sources fine.")
    stale = sorted(t for t, v in price_outcomes.items() if v == "failed")
    if stale and market != "outage":
        lines.append("stale prices: " + ", ".join(stale) + " — their checks are suspended, not passed.")
    if not stale and market == "open":
        lines.append("all sources fresh.")
    line = disk_free_line()
    if line:
        lines.append(line)
    return tuple(lines)


def disk_free_line() -> str | None:
    usage = shutil.disk_usage(db.state_dir())
    if usage.free < DISK_FLOOR_BYTES:
        return (f"disk free {usage.free / 1024**3:.1f} GB — below 2 GB; "
                "an append-only box that fills its disk fails silently (§11.6).")
    return None


def _late_banner(as_of: datetime) -> str:
    return f"catch-up run — generated {db.to_iso(as_of)}"


def opportunity_lines(conn, *, as_of) -> tuple[tuple[contexts.OpportunityLine, ...], int]:
    """E.4 daily comparisons. on_sale: held framework positions with a live INTACT thesis,
    multiple <= (1 - discount) * fair_band_mid. fair_entry: WATCH items (stage
    gate_approved_waiting), multiple <= fair_band_high. A stale/empty/non-positive
    denominator or stale price SUSPENDS that ticker's line with a printed note (MA-3).
    Sorted by position weight desc (held first); renderer shows top 3 + tail."""
    discount = config_mod.get_float(conn, "buy_opportunity_discount_pct") / 100.0
    lines: list[tuple[float, contexts.OpportunityLine]] = []
    snap = db.fetch_latest_snapshot(conn)
    positions = mirror.advice_positions(conn, snap["snapshot_id"]) if snap else []
    smap = db.fetch_current_symbol_map(conn)

    def one(ticker: str, thesis_id: str, kind: str, weight: float) -> None:
        tv = db.fetch_current_thesis_version(conn, thesis_id)
        armed = db.fetch_armed_triggers(conn, thesis_id)
        n_pass = sum(1 for t in armed
                     if (c := db.fetch_latest_trigger_check(conn, t["trigger_id"]))
                     and c["result"] == "PASS")
        low, high = tv["fair_band_low"], tv["fair_band_high"]
        denom = store.denominator_per_share(conn, ticker, as_of=as_of)
        price = store.latest_close(conn, ticker, as_of=as_of)
        suspended = None
        if denom is None or not denom.usable() or denom.value <= 0:
            suspended = (f"{ticker}: check suspended — denominator stale/empty/non-positive "
                         "(MA-3); suspension stated, silence never means no opportunity.")
        elif price is None or not price.usable():
            suspended = f"{ticker}: check suspended — price stale (MA-3)."
        if suspended:
            lines.append((weight, contexts.OpportunityLine(
                ticker=ticker, multiple=None, band_low=low, band_high=high,
                thesis_version=tv["version"], triggers_pass=n_pass, triggers_total=len(armed),
                kind=kind, suspended_note=suspended)))
            return
        multiple = price.value.close / denom.value
        mid = (low + high) / 2.0
        hit = (multiple <= (1.0 - discount) * mid) if kind == "on_sale" else (multiple <= high)
        if hit:
            lines.append((weight, contexts.OpportunityLine(
                ticker=ticker, multiple=multiple, band_low=low, band_high=high,
                thesis_version=tv["version"], triggers_pass=n_pass, triggers_total=len(armed),
                kind=kind, suspended_note=None)))

    for p in positions:
        if p.instrument_type == "cash" or not p.yf_ticker:
            continue
        tid = register.live_thesis_for(conn, p.symbol)
        if tid is None:
            continue
        status = db.fetch_current_thesis_status(conn, tid)
        if status is None or status["status"] != "intact":
            continue
        one(p.yf_ticker, tid, "on_sale", p.weight)

    for item in db.fetch_watchlist(conn, stage="gate_approved_waiting"):
        if not item["thesis_ref"]:
            continue
        one(smap.get(item["ticker"], item["ticker"]), item["thesis_ref"], "fair_entry", 0.0)

    lines.sort(key=lambda pair: -pair[0])
    ordered = tuple(l for _, l in lines)
    return ordered, max(0, len(ordered) - 3)


def sweep_ask_deadlines(conn, *, clock: Clock, run_id: int) -> list[str]:
    """asks.sweep_deadlines marks counted-unanswered past effective_deadline (pause-aware,
    D.6 — frozen never fires); this applies the per-kind consequence (D.5/B.3):
    A -> alert_ignored auto-journal (once; the alert row stays open and heads the letter)
    Q -> trigger_check UNVERIFIABLE appended for its trigger (B.3.4)
    F/V/R/N -> the unanswered status itself is the record (skip counters derive from it)."""
    notes: list[str] = []
    for outcome in asks.sweep_deadlines(conn, as_of=clock.now()):
        a = outcome.ask
        if a.kind == "A":
            existing = [e for e in db.fetch_journal_entries(conn, decision_type="alert_ignored")
                        if e["ask_ref"] == a.ask_id]
            if not existing:
                journal.append(conn, EntryIn(
                    decision_type="alert_ignored", ticker=None, thesis_ref=a.thesis_ref,
                    system_recommendation="alert unanswered by deadline; recorded, not judged today (B.3.3)",
                    owner_action="no_action", inputs_ref=run_id, ask_ref=a.ask_id,
                    actor="system"), clock=clock)
                notes.append(f"{a.ask_id}: alert_ignored journaled")
        elif a.kind == "Q" and a.trigger_ref is not None:
            db.append_trigger_check(conn, dict(
                trigger_id=a.trigger_ref, run_id=run_id, checked_at=db.to_iso(clock.now()),
                result="UNVERIFIABLE", observed_value=None, headroom=None, evaluable_from=None))
            notes.append(f"{a.ask_id}: UNVERIFIABLE recorded")
    conn.commit()
    return notes


def open_loop_lines(conn, *, as_of: datetime) -> tuple[contexts.OpenLoopLine, ...]:
    """Open loops for the letter: ignored-alert asks FIRST (B.3.3 heads the letter),
    then open/reprompted asks, oldest first."""
    head: list[contexts.OpenLoopLine] = []
    rest: list[contexts.OpenLoopLine] = []
    open_alert_ids = {r["alert_id"] for r in db.fetch_open_alerts(conn)}

    def age(created_at: str) -> int:
        return (as_of - db.from_iso(created_at)).days

    for row in db.fetch_unanswered_asks(conn, kind="A"):
        if row["alert_ref"] in open_alert_ids:
            head.append(contexts.OpenLoopLine(
                ask_id=row["ask_id"],
                label=f"ALERT IGNORED — {row['thesis_ref'] or ''} — decision still open",
                age_days=age(row["created_at"])))
    for a in asks.open_asks(conn):
        label = {"A": "alert decision open", "Q": "prompted question waiting",
                 "R": "reconciliation waiting", "F": "re-affirmation waiting",
                 "V": "verdict follow-up waiting", "N": "note invited"}[a.kind]
        rest.append(contexts.OpenLoopLine(ask_id=a.ask_id, label=f"{label} ({a.ask_id})",
                                          age_days=age(db.to_iso(a.created_at))))
    head.sort(key=lambda l: -l.age_days)
    rest.sort(key=lambda l: -l.age_days)
    return tuple(head + rest)


# ---- stubs completed by later tasks ------------------------------------------------
def events_line(conn, *, as_of):                             # P6.7
    return None
def respool_lagging_events(conn, *, as_of, state_dir):       # P6.7
    return 0
def is_pulse_day(as_of: datetime) -> bool:                   # P6.8 tests this properly
    return as_of.astimezone(AMS).weekday() in (6, 0)         # Sun, Mon
def build_pulse_context(conn, *, as_of, late):               # P6.8
    loops = open_loop_lines(conn, as_of=as_of)
    return contexts.DailyContext(kind="pulse", as_of=as_of, header=None,
                                 verdict_line=f"markets closed — nothing to check; {len(loops)} open items; data health ok",
                                 opportunities=(), more_opportunities=0, events_line=None,
                                 data_lines=(), open_loops=loops, open_items_count=len(loops),
                                 generated_at=as_of, late_banner=_late_banner(as_of) if late else None)
def letter_suppressed(conn, *, as_of) -> bool:               # P6.8
    return False
