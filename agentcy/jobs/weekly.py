"""Weekly job (D.2). Saturday 08:00 Europe/Amsterdam. The authoritative D.3 earnings
detector (statement fingerprints) and the B.2 officer-diff tripwire both live here:
detection appends an event row and writes an atomic spool file; the path-unit-driven
event job does the actual check (§1.5). run_one lands in P6.12."""
from __future__ import annotations

import dataclasses
from datetime import timedelta
from pathlib import Path

import pandas as pd

from agentcy import (archive, asks, cluster, config as config_mod, db, events, mirror,
                     register, study, triggers)
from agentcy.clock import Clock, SystemClock
from agentcy.events import EventRequest
from agentcy.fetch import store, yf
from agentcy.fetch.yf import FetchFailed
from agentcy.jobs import keyboards, runner
from agentcy.render import alert as render_alert_mod, contexts
from agentcy.render import weekly as render_weekly_mod
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


def dividend_lines(conn, *, as_of) -> tuple[tuple[str, ...], bool]:
    """BUF-2: receipts = quantity-at-snapshot x dividend events since the last snapshot,
    from the price_cache dividend column, converted at latest FX, freshness-stamped.
    reinvest reminder when receipts exist and cash sits above the band floor."""
    snap = db.fetch_latest_snapshot(conn)
    if snap is None:
        return (), False
    since = snap["as_of"][:10]
    lines: list[str] = []
    for p in mirror.advice_positions(conn, snap["snapshot_id"]):
        if p.instrument_type == "cash" or not p.yf_ticker:
            continue
        rows = [r for r in db.fetch_v_price(conn, p.yf_ticker)
                if r["bar_date"] > since and r["dividend"] > 0]
        if not rows:
            continue
        per_share = sum(r["dividend"] for r in rows)
        fx = store.fx_rate_eur(conn, p.native_currency, as_of=as_of)
        rate = fx.value if fx is not None else 1.0
        amt = p.quantity * per_share * rate
        newest = max(r["fetched_at"] for r in rows)
        lines.append(f"{p.yf_ticker}: €{amt:.2f} received since {since} "
                     f"(price data as of {newest[:10]}). "
                     "Constitution default: reinvest unless income is needed.")
    if not lines:
        return (), False
    bal = mirror.balance(conn, as_of=as_of)
    floor = config_mod.get_float(conn, "cash_band_low_pct")
    return tuple(lines), bal.cash_pct > floor


def reaffirmation_asks(conn, *, run_id: int, clock: Clock) -> list[str]:
    """A.1 anniversary re-affirmations -> one F ask per due thesis (tg-spec §3.5 step 1);
    one open F per thesis max."""
    open_f = {a["thesis_ref"] for a in db.fetch_open_asks(conn, kind="F")}
    minted = []
    for tid in register.anniversaries_due(conn, as_of=clock.now()):
        if tid in open_f:
            continue
        tv = db.fetch_current_thesis_version(conn, tid)
        ask = asks.mint(conn, kind="F",
                        prompt=(f"Annual re-affirmation — {tid}. Three judgments to re-affirm; "
                                f"your answers only; I never set these (FR9). "
                                f"1/3 — Conviction. You set this to {tv['conviction'].upper()}. Still?"),
                        options=["same", "change"], thesis_ref=tid, run_id=run_id, clock=clock)
        minted.append(ask.ask_id)
    conn.commit()
    return minted


def unverifiable_headlines(conn, *, as_of) -> tuple[str, ...]:
    """B.3.4: 3 consecutive UNVERIFIABLE weeks escalate to the weekly HEADLINE."""
    out = []
    for trig in db.fetch_armed_triggers(conn):
        weeks = triggers.unverifiable_weeks(conn, trig["trigger_id"], as_of=as_of)
        if weeks >= 3:
            out.append(f"UNVERIFIABLE {weeks} weeks — {trig['thesis_id']} T{trig['trigger_id']}: "
                       f"\"{trig['statement']}\" Suspended is not green.")
    return tuple(out)


def study_block(conn, *, run_id: int, clock: Clock) -> contexts.StudyContext:
    """F.3 digest + the optional circle-note N ask (§3.9) + rotation advance."""
    ctx = study.build_digest(conn, as_of=clock.now())
    note_ask = asks.mint(conn, kind="N",
                         prompt="Circle note — did anything this week expand or shrink the circle? "
                                "(write or skip; skipping is fine)",
                         options=[], expects_freetext=True, run_id=run_id, clock=clock)
    state = db.fetch_study_state(conn)
    tid = register.live_thesis_for(conn, ctx.restudy_ticker) or ctx.restudy_ticker
    study.advance_rotation(conn, thesis_id=tid,
                           model_index=state["mental_model_index"] + 1, clock=clock)
    conn.commit()
    return dataclasses.replace(ctx, circle_note_ask_id=note_ask.ask_id)


def broken_but_held(conn, *, as_of) -> tuple[str, ...]:
    """Broken theses whose ticker is still in the latest snapshot -> weekly renag lines."""
    snap = db.fetch_latest_snapshot(conn)
    held = {p.symbol for p in (mirror.advice_positions(conn, snap["snapshot_id"]) if snap else [])}
    out = []
    for symbol in sorted(held):
        tid = register.live_thesis_for(conn, symbol)
        if tid is None:
            continue
        st = db.fetch_current_thesis_status(conn, tid)
        if st is not None and st["status"] == "broken":
            out.append(f"{symbol}: thesis {tid} is BROKEN and the position is still held — "
                       "the standing advice is unchanged (cost basis ignored).")
    return tuple(out)


def revalidation_lines(conn, *, as_of) -> tuple[str, ...]:
    """D.2 check 3: per holding one line — status, version, headroom scorecard."""
    snap = db.fetch_latest_snapshot(conn)
    out = []
    for p in (mirror.advice_positions(conn, snap["snapshot_id"]) if snap else []):
        if p.instrument_type == "cash":
            continue
        tid = register.live_thesis_for(conn, p.symbol)
        if tid is None:
            continue
        st = db.fetch_current_thesis_status(conn, tid)
        tv = db.fetch_current_thesis_version(conn, tid)
        rows = triggers.headroom_table(conn, tid, as_of=as_of)
        score = ", ".join(f"T{r.trigger_id}:{r.result}"
                          + (f" (headroom {r.headroom:+.1f})" if r.headroom is not None else "")
                          for r in rows) or "no armed triggers"
        out.append(f"{p.symbol} — {st['status'] if st else 'draft'} (v{tv['version']}) · {score}")
    return tuple(out)


def main(*, clock: Clock | None = None, state_dir: Path | None = None) -> int:
    clock = clock or SystemClock()
    state_dir = state_dir or db.state_dir()
    conn = db.open_db(state_dir)
    try:
        return runner.sweep_and_run(conn, RUN_TYPE, run_one, clock=clock, state_dir=state_dir)
    finally:
        conn.close()


def run_one(conn, handle, *, clock: Clock, state_dir: Path) -> tuple[str, dict]:
    batch = refresh_batch(conn, run_id=handle.run_id, clock=clock, state_dir=state_dir)
    fired = run_trigger_tests(conn, run_id=handle.run_id, clock=clock)
    qs = queue_prompted_questions(conn, run_id=handle.run_id, clock=clock)
    sweeps = housekeeping(conn, run_id=handle.run_id, clock=clock)         # P6.13; stub {} below
    ctx = build_weekly_context(conn, as_of=clock.now(), clock=clock, run_id=handle.run_id,
                               refresh_notes=batch["data_health"])
    series, doc = render_weekly_mod.render_weekly(ctx)
    report_id = archive.archive_and_store(conn, doc, run_id=handle.run_id, report_type="weekly",
                                          period=handle.scheduled_for,
                                          freshness={"notes": batch["data_health"]}, clock=clock)
    doc_path = db.fetch_report(conn, report_id)["archive_path"]
    for i, msg in enumerate(series, start=1):
        runner.enqueue_rendered(conn, msg,
                                base_key=outbox.scheduled_key(RUN_TYPE, handle.scheduled_for, f"msg{i}"),
                                kind="weekly_msg", run_id=handle.run_id, clock=clock,
                                artifact_ref=report_id)
    runner.enqueue_rendered(conn, doc,
                            base_key=outbox.scheduled_key(RUN_TYPE, handle.scheduled_for, "doc"),
                            kind="weekly_doc", run_id=handle.run_id, clock=clock,
                            artifact_ref=report_id, document_path=doc_path)
    conn.commit()
    status = "degraded" if batch["data_health"] else "ok"
    return status, {"fired": fired["fired_alert_ids"], "prompted": qs,
                    "sweeps": sweeps, "data_health": batch["data_health"]}


def build_weekly_context(conn, *, as_of, clock: Clock, run_id: int,
                         refresh_notes: list[str]) -> contexts.WeeklyContext:
    snap = db.fetch_latest_snapshot(conn)
    positions = mirror.advice_positions(conn, snap["snapshot_id"]) if snap else []
    designations = db.fetch_latest_designations(conn)
    rows = []
    total = (snap["cash_balance_eur"] if snap else 0.0)
    for p in positions:
        total += p.mv_eur
        if p.instrument_type == "cash":
            continue
        tid = register.live_thesis_for(conn, p.symbol)
        tv = db.fetch_current_thesis_version(conn, tid) if tid else None
        st = db.fetch_current_thesis_status(conn, tid) if tid else None
        des = designations.get(p.symbol)
        armed = db.fetch_armed_triggers(conn, tid) if tid else []
        n_armed = len(armed)
        n_pass = sum(1 for t in armed
                     if (c := db.fetch_latest_trigger_check(conn, t["trigger_id"]))
                     and c["result"] == "PASS")
        rows.append(contexts.PortfolioRow(
            ticker=p.symbol, weight_pct=round(p.weight * 100, 1), mv_eur=p.mv_eur,
            framework_status=(des["framework_status"] if des else "backfill_pending"),
            thesis_status=(st["status"] if st else None),
            thesis_version=(tv["version"] if tv else None),
            conviction=(tv["conviction"] if tv else None), sector_label=None,
            anchor_multiple=None,
            band_low=(tv["fair_band_low"] if tv else None),
            band_high=(tv["fair_band_high"] if tv else None),
            trigger_scorecard=f"{n_pass}/{n_armed} pass"))
    returns, weights = _returns_frame(conn, positions)
    bal = mirror.balance(conn, as_of=as_of, returns_local=returns)   # populates n_eff (§E.5)
    clus = cluster.compute_clusters(returns, weights,
                                    threshold=config_mod.get_float(conn, "correlation_threshold"))
    div_lines, reinvest = dividend_lines(conn, as_of=as_of)
    unver = unverifiable_headlines(conn, as_of=as_of)
    open_alerts = db.fetch_open_alerts(conn)
    decisions = _decision_blocks(conn)
    bq = mirror.backfill_queue(conn, as_of=as_of)
    reaff_due = tuple(register.anniversaries_due(conn, as_of=as_of))
    celebrated = not (open_alerts or unver or broken_but_held(conn, as_of=as_of) or decisions)
    headline = ("No action needed. The document has the full picture when you want it."
                if celebrated else
                f"{len(open_alerts)} open review(s), {len(unver)} escalation(s), "
                f"{len(decisions)} decision(s) waiting.")
    outside_pct = bal.outside_framework_pct
    return contexts.WeeklyContext(
        as_of=as_of, headline_verdict=" ".join([headline] + list(unver)), celebrated=celebrated,
        decisions=tuple(d for d in decisions if not d.ask_id.startswith("Q")),
        portfolio=tuple(rows), total_eur=total,
        revalidations=revalidation_lines(conn, as_of=as_of),
        backfill_queue_line=(f"backfill next in queue: {bq[0]} ({len(bq)} pending, largest first)"
                             if bq else None),
        broken_but_held=broken_but_held(conn, as_of=as_of), reaffirmations_due=reaff_due,
        balance=bal, clusters=clus, dividend_lines=div_lines, reinvest_reminder=reinvest,
        loosening_echoes=tuple(str(dict(r)) for r in register.loosening_echoes(conn, as_of=as_of)),
        outside_framework_line=(f"outside framework: {outside_pct:.1f}% of book "
                                f"(cap {config_mod.get_float(conn, 'outside_framework_cap_pct'):.0f}%)"),
        watchlist_lines=_watchlist_lines(conn, as_of=as_of),
        prompted_questions=tuple(d for d in decisions if d.ask_id.startswith("Q")),
        study=study_block(conn, run_id=run_id, clock=clock),
        data_health=tuple(refresh_notes), generated_at=as_of)


def _decision_blocks(conn) -> list[contexts.DecisionBlock]:
    """Open Q/F/V asks as msg-2 decision blocks, each with its stable-ID keyboard (§2.2).
    The kind IS the first character of ask_id (D.5 ID format), so no extra lookup is needed;
    A-asks ride their alert message (P6.10), not msg 2."""
    blocks = []
    for kind, kb in (("Q", keyboards.q_keyboard), ("F", keyboards.reaff_keyboard),
                     ("V", keyboards.v_keyboard)):
        for a in db.fetch_open_asks(conn, kind=kind):
            blocks.append(contexts.DecisionBlock(
                ask_id=a["ask_id"], heading=f"{a['ask_id']} — decision waiting",
                body=a["prompt"], reply_markup_json=kb(a["ask_id"])))
    return blocks


def _watchlist_lines(conn, *, as_of) -> tuple[str, ...]:
    """G.2 §6: approved -> distance to fair entry; raw -> name + days-to-expiry ONLY."""
    lines = []
    for item in db.fetch_watchlist(conn, stage="gate_approved_waiting"):
        lines.append(f"{item['ticker']}: WATCH — fair-entry check armed daily")
    for item in db.fetch_watchlist(conn, stage="raw"):
        left = 90 - (as_of - db.from_iso(item["added_at"])).days
        lines.append(f"{item['ticker']}: raw, {left} days to expiry")
    return tuple(lines)


def _returns_frame(conn, positions):
    """E.5 input: 252d local-currency daily returns + weights for mappable invested positions,
    keyed by symbol so the one frame feeds both mirror.balance (n_eff, symbol-keyed weights)
    and the weekly cluster block consistently."""
    frames = {}
    weights = {}
    for p in positions:
        if p.instrument_type == "cash" or not p.yf_ticker:
            continue
        rows = db.fetch_v_price(conn, p.yf_ticker)
        if rows:
            s = pd.Series({r["bar_date"]: r["adj_close"] for r in rows}).sort_index()
            frames[p.symbol] = s.pct_change().dropna().tail(252)
            weights[p.symbol] = p.weight
    return pd.DataFrame(frames), weights


def housekeeping(conn, *, run_id: int, clock: Clock) -> dict:   # P6.13
    return {}
