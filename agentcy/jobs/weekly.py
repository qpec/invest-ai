"""Weekly job (D.2). Saturday 08:00 Europe/Amsterdam. The authoritative D.3 earnings
detector (statement fingerprints) and the B.2 officer-diff tripwire both live here:
detection appends an event row and writes an atomic spool file; the path-unit-driven
event job does the actual check (§1.5). run_one lands in P6.12."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from agentcy import asks, db, events, mirror, triggers
from agentcy.clock import Clock
from agentcy.events import EventRequest
from agentcy.fetch import store, yf
from agentcy.fetch.yf import FetchFailed
from agentcy.jobs import runner
from agentcy.render import alert as render_alert_mod, contexts
from agentcy.tg import outbox

RUN_TYPE = "weekly"


def _held_tickers(conn) -> list[str]:
    """Mappable non-cash holdings (D.2 inputs). Refresh covers all mappable non-cash
    holdings: backfill holdings are monitored for balance only (C.6), but their statements
    still archive so the backfill Gate dossier has data — the simplest compliant reading of
    D.2 'quarterly statements per holding'."""
    snap = db.fetch_latest_snapshot(conn)
    if snap is None:
        return []
    out = []
    for p in mirror.advice_positions(conn, snap["snapshot_id"]):
        if p.instrument_type == "cash" or not p.yf_ticker:
            continue
        out.append(p.yf_ticker)
    return out


def _mint_and_spool(conn, req: EventRequest, *, run_id: int, state_dir: Path) -> None:
    db.append_event(conn, dict(yf_ticker=req.yf_ticker, source=req.source, kind=req.kind,
                               note=req.note, detected_at=req.detected_at,
                               detected_late=int(req.detected_late), run_id=run_id))
    events.spool_write(state_dir, req)


def refresh_batch(conn, *, run_id: int, clock: Clock, state_dir: Path) -> dict:
    """Per held ticker: bars, statements (fingerprint diff -> earnings event), shares,
    officers (diff -> mgmt event), calendar. Every step per-ticker try/except: one
    failing source degrades that line, never the batch."""
    fetched_at = db.to_iso(clock.now())
    health: list[str] = []
    spooled: list[str] = []
    for t in _held_tickers(conn):
        try:
            frame = yf.fetch_daily_bars(t, state_dir=state_dir)
            store.store_price_bars(conn, t, frame, run_id=run_id, fetched_at=fetched_at)
        except FetchFailed:
            health.append(f"{t} prices: fetch failed — STALE")
        had_baseline = bool(db.fetch_statement_periods(conn, t, "income"))
        try:
            stmts = yf.fetch_statements(t, state_dir=state_dir)
            new_fps = store.store_statements(conn, t, stmts, run_id=run_id, fetched_at=fetched_at)
            if new_fps and had_baseline:
                req = EventRequest(yf_ticker=t, source="fingerprint", kind="earnings",
                                   note=f"{len(new_fps)} new statement fingerprint(s)",
                                   detected_at=db.to_iso(clock.now()))
                _mint_and_spool(conn, req, run_id=run_id, state_dir=state_dir)
                spooled.append(t)
        except FetchFailed:
            health.append(f"{t} statements: fetch failed — fundamental triggers STALE (suspended, not passed)")
        try:
            series = yf.fetch_shares_full(t, state_dir=state_dir)
            store.store_shares(conn, t, series, fetched_at=fetched_at)
        except FetchFailed:
            health.append(f"{t} shares: fetch failed — dilution check STALE")
        try:
            officers = yf.fetch_officers(t, state_dir=state_dir)
            if store.store_officers(conn, t, officers, fetched_at=fetched_at):
                req = EventRequest(yf_ticker=t, source="officer_diff", kind="mgmt",
                                   note="companyOfficers fingerprint changed (B.2 tripwire — best-effort per MA-6)",
                                   detected_at=db.to_iso(clock.now()))
                _mint_and_spool(conn, req, run_id=run_id, state_dir=state_dir)
                spooled.append(t)
        except FetchFailed:
            health.append(f"{t} officers: fetch failed — tripwire silent this week (best-effort, MA-6)")
        try:
            expected = yf.fetch_calendar(t, state_dir=state_dir)
            if expected:
                store.store_calendar(conn, t, expected, run_id=run_id, fetched_at=fetched_at)
        except FetchFailed:
            health.append(f"{t} calendar: fetch failed (preview only, MA-7)")
    conn.commit()
    return {"data_health": health, "spooled": spooled}


def run_trigger_tests(conn, *, run_id: int, clock: Clock) -> dict:
    """D.2 check 2: evaluate every armed weekly-cadence trigger; each FIRE goes through
    triggers.fire (thesis -> under_review, alert + A-ask). >1 FIRE in one run = a storm:
    shared storm_key, one bundled message ranked by weight (B.3.5). The bundle is enqueued
    under alert_key(min alert_id) — alerts retry until delivered."""
    outcomes = triggers.evaluate_armed(conn, cadence="weekly", as_of=clock.now(), run_id=run_id)
    fires = [o for o in outcomes if str(o.result) == "FIRE"]
    fired_ids: list[int] = []
    if fires:
        storm_key = (f"storm:{clock.now().date().isoformat()}" if len(fires) > 1 else None)
        for o in fires:
            already = [a for a in db.fetch_open_alerts(conn) if a["trigger_id"] == o.trigger_id]
            if already:                                   # crash re-run guard: never double-alert
                continue
            fired_ids.append(triggers.fire(conn, o, clock=clock, run_id=run_id, storm_key=storm_key))
        if fired_ids:
            ctx = build_alert_context(conn, fired_ids, as_of=clock.now())
            r = render_alert_mod.render_alert(ctx)
            runner.enqueue_rendered(conn, r, base_key=outbox.alert_key(min(fired_ids)),
                                    kind="alert", run_id=run_id, clock=clock)
    conn.commit()
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[str(o.result)] = counts.get(str(o.result), 0) + 1
    return {"fired_alert_ids": fired_ids, "outcome_counts": counts}


def build_alert_context(conn, alert_ids: list[int], *, as_of) -> contexts.AlertContext:
    """G.3 card(s). Owner-quoted fields (committed statement, ten-year excerpt) go verbatim;
    the renderer places them in owner_spans (lint-exempt, §8)."""
    snap = db.fetch_latest_snapshot(conn)
    weights = {p.yf_ticker: p.weight for p in
               (mirror.advice_positions(conn, snap["snapshot_id"]) if snap else [])}
    items = []
    deadline = None
    for aid in alert_ids:
        alert = db.fetch_alert(conn, aid)
        deadline = alert["deadline"]
        trig = next(t for t in db.fetch_armed_triggers(conn, alert["thesis_id"])
                    if t["trigger_id"] == alert["trigger_id"])
        tv = db.fetch_current_thesis_version(conn, alert["thesis_id"])
        thesis = db.fetch_thesis(conn, alert["thesis_id"])
        check = db.fetch_latest_trigger_check(conn, trig["trigger_id"])
        ask = next(a for a in db.fetch_open_asks(conn, kind="A") if a["alert_ref"] == aid)
        ticker = thesis["ticker"]
        items.append(contexts.AlertItemContext(
            ticker=ticker, weight_pct=round(weights.get(ticker, 0.0) * 100, 1),
            trigger_label=f"T{trig['trigger_id']} ({trig['type']})",
            committed_statement_owner=trig["statement"],
            committed_version=trig["introduced_version"], committed_at=tv["created_at"][:10],
            what_happened=(f"observed {check['observed_value']}" if check and
                           check["observed_value"] is not None else "see check record"),
            baseline_note=None, price_move_pct=_price_move_pct(conn, ticker, as_of=as_of),
            ten_year_excerpt_owner=tv["ten_year_statement"], ask_id=ask["ask_id"]))
    items.sort(key=lambda i: -i.weight_pct)               # storms ranked by weight (B.3.5)
    return contexts.AlertContext(deadline_label=f"decision by {deadline[:10]}",
                                 items=tuple(items), generated_at=as_of)


def _price_move_pct(conn, yf_ticker: str, *, as_of) -> str:
    """~30d move, stated flatly and disowned by the WHAT THIS IS NOT block; 'n/a' on thin data."""
    rows = db.fetch_v_price(conn, yf_ticker)
    if len(rows) < 2:
        return "n/a"
    closes = [r["close"] for r in rows[-22:]]
    return f"{(closes[-1] / closes[0] - 1) * 100:+.1f}%"


def queue_prompted_questions(conn, *, run_id: int, clock: Clock, cadence: str = "weekly") -> list[str]:
    """Mint one Q ask per armed prompted trigger of this cadence without an open Q (D.2 check 2 /
    tg-spec §3.2). The weekly job queues weekly-cadence triggers; the event job passes
    cadence='event' (R5)."""
    open_q_refs = {a["trigger_ref"] for a in db.fetch_open_asks(conn, kind="Q")}
    minted: list[str] = []
    for trig in db.fetch_armed_triggers(conn):
        if trig["check_method"] != "prompted" or trig["cadence"] != cadence:
            continue
        if trig["trigger_id"] in open_q_refs:
            continue
        ask = asks.mint(conn, kind="Q",
                        prompt=(f"Prompted check — {trig['thesis_id']} — T{trig['trigger_id']}. "
                                f"Committed question (your words): \"{trig['statement']}\" "
                                "This is a yes/no you pre-committed to answer. No price is involved."),
                        options=["yes", "no", "cant"], thesis_ref=trig["thesis_id"],
                        trigger_ref=trig["trigger_id"],
                        deadline=db.to_iso(clock.now() + timedelta(days=7)),
                        run_id=run_id, clock=clock)
        minted.append(ask.ask_id)
    conn.commit()
    return minted
