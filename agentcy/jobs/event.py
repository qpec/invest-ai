"""Event job (D.3). Fired by agentcy-event.path (DirectoryNotEmpty). Drains the spool
SEQUENTIALLY: each file moved out of the watched dir BEFORE acting (§1.5), its own RunLog
row keyed {ticker}:{detected_at}. Fresh statements bypass the cache (still paced, appended
to the archive); the full armed trigger set is re-tested; event-cadence prompted questions
are queued; quiet -> event report + next-letter line; fire -> alert path. Never opens
the benchmark store / imports quantstats (invariants 4/7)."""
from __future__ import annotations

from pathlib import Path

from agentcy import archive, db, events, register, runlog, triggers
from agentcy.clock import Clock, SystemClock
from agentcy.events import EventRequest, scheduled_for
from agentcy.fetch import store, yf
from agentcy.fetch.yf import FetchFailed
from agentcy.jobs import runner
from agentcy.jobs import weekly as weekly_mod           # reuse build_alert_context + Q-queueing
from agentcy.render import alert as render_alert_mod, contexts
from agentcy.render import event as render_event_mod
from agentcy.runlog import RunHandle
from agentcy.tg import outbox

RUN_TYPE = "event"


def fetch_fresh_statements(conn, yf_ticker: str, *, run_id: int, clock: Clock, state_dir: Path) -> list[str]:
    """D.3: bypass the FRESH-for-a-week cache — fetch statements now (still paced by the
    box-wide yahoo lock), append on unseen fingerprint. Returns new fingerprints. FetchFailed
    -> [] and the report notes the 7-day data-lag retry (the daily job re-spools, P6.7)."""
    try:
        stmts = yf.fetch_statements(yf_ticker, state_dir=state_dir)
    except FetchFailed:
        return []
    return store.store_statements(conn, yf_ticker, stmts, run_id=run_id,
                                  fetched_at=db.to_iso(clock.now()))


def _thesis_for(conn, yf_ticker: str) -> str | None:
    sym = next((s for s, t in db.fetch_current_symbol_map(conn).items() if t == yf_ticker), yf_ticker)
    return register.live_thesis_for(conn, sym)


def check_one(conn, req: EventRequest, handle: RunHandle, *, clock: Clock, state_dir: Path) -> tuple[str, dict]:
    """One spooled request: fresh statements -> full trigger set -> queue Q asks -> deliver."""
    run_id = handle.run_id
    thesis_id = _thesis_for(conn, req.yf_ticker)
    new_fps = fetch_fresh_statements(conn, req.yf_ticker, run_id=run_id, clock=clock, state_dir=state_dir)
    data_lag = not new_fps and req.kind == "earnings"
    outcomes = (triggers.evaluate_armed(conn, cadence="event", thesis_id=thesis_id,
                                        as_of=clock.now(), run_id=run_id) if thesis_id else [])
    fires = [o for o in outcomes if str(o.result) == "FIRE"]
    prompted = (weekly_mod.queue_prompted_questions(conn, run_id=run_id, clock=clock, cadence="event")
                if thesis_id else [])
    if fires:                                             # FIRE -> alert path, NOT an event report (D.3)
        fired_ids = []
        for o in fires:
            if any(a["trigger_id"] == o.trigger_id for a in db.fetch_open_alerts(conn)):
                continue
            fired_ids.append(triggers.fire(conn, o, clock=clock, run_id=run_id))
        if fired_ids:
            ctx = weekly_mod.build_alert_context(conn, fired_ids, as_of=clock.now())
            runner.enqueue_rendered(conn, render_alert_mod.render_alert(ctx),
                                    base_key=outbox.alert_key(min(fired_ids)), kind="alert",
                                    run_id=run_id, clock=clock)
        conn.commit()
        return "ok", {"fired": fired_ids, "prompted": prompted}
    # quiet (or data-lag) outcome -> archived event report + one line in the next daily letter (D.3):
    ctx = contexts.EventContext(
        ticker=req.yf_ticker, event_kind=req.kind, owner_initiated=(req.source == "owner"),
        triggers_pass=sum(1 for o in outcomes if str(o.result) == "PASS"),
        triggers_total=len(outcomes), data_lag=data_lag,
        retry_note=("statements not yet updated; retrying daily for 7 days" if data_lag else None),
        prompted_ask_ids=tuple(prompted), generated_at=clock.now())
    r = render_event_mod.render_event(ctx)
    period = f"{req.yf_ticker}:{req.detected_at}"
    report_id = archive.archive_and_store(conn, r, run_id=run_id, report_type="event",
                                          period=period, freshness={}, clock=clock)
    # Only push an immediate message for owner-initiated /event (tg-spec §2.4); detector-quiet
    # outcomes fold silently into tomorrow's letter (P6.7 reads the archived event report).
    if req.source == "owner":
        runner.enqueue_rendered(conn, r, base_key=outbox.event_key(req.yf_ticker, req.detected_at, "report"),
                                kind="event", run_id=run_id, clock=clock, artifact_ref=report_id)
    conn.commit()
    # keys below are the fold-in contract daily.events_line() reads (P6.7): quiet gate +
    # the "N/M" triggers_pass string it renders into the next letter.
    return "ok", {"fired": [], "prompted": prompted, "report_id": report_id, "data_lag": data_lag,
                  "quiet": True, "triggers_pass": f"{ctx.triggers_pass}/{ctx.triggers_total}"}


def run_one(conn, handle: RunHandle, *, clock: Clock, state_dir: Path) -> tuple[str, dict]:
    """Adapter for runner.sweep_and_run when a single event key is swept (crash re-claim).
    The request is reconstructed from the key; normal fire is via drain() below."""
    ticker, detected_at = handle.scheduled_for.split(":", 1)
    req = EventRequest(yf_ticker=ticker, source="fingerprint", kind="earnings",
                       note=None, detected_at=detected_at, detected_late=True)
    return check_one(conn, req, handle, clock=clock, state_dir=state_dir)


def drain(conn, *, clock: Clock, state_dir: Path) -> int:
    """§1.5 drain: for each spooled file, move it out FIRST (spool_take -> done/ or failed/),
    then start its own RunLog key and run check_one under the event lock. A poison file lands
    in failed/ and never re-triggers the path unit."""
    for path in events.spool_paths(state_dir):
        req = events.spool_take(state_dir, path)          # moved to done/ or failed/ before we act
        if req is None:                                   # poison file -> failed/, keep draining
            continue
        key = scheduled_for(req)
        if runlog.is_finished(conn, RUN_TYPE, key):
            continue
        with runlog.run_lock(state_dir, RUN_TYPE):
            handle = runlog.start(conn, RUN_TYPE, key, clock=clock, late=req.detected_late)
            conn.commit()
            try:
                status, outputs = check_one(conn, req, handle, clock=clock, state_dir=state_dir)
            except Exception as exc:
                runner._on_job_exception(conn, handle, clock=clock, exc=exc)
                raise
            runlog.finish(conn, handle.run_id, status=status, outputs=outputs, clock=clock)
            conn.commit()
    return 0


def main(*, clock: Clock | None = None, state_dir: Path | None = None) -> int:
    clock = clock or SystemClock()
    state_dir = state_dir or db.state_dir()
    conn = db.open_db(state_dir)
    try:
        return drain(conn, clock=clock, state_dir=state_dir)
    finally:
        conn.close()
