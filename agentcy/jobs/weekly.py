"""Weekly job (D.2). Saturday 08:00 Europe/Amsterdam. The authoritative D.3 earnings
detector (statement fingerprints) and the B.2 officer-diff tripwire both live here:
detection appends an event row and writes an atomic spool file; the path-unit-driven
event job does the actual check (§1.5). run_one lands in P6.12."""
from __future__ import annotations

from pathlib import Path

from agentcy import db, events, mirror
from agentcy.clock import Clock
from agentcy.events import EventRequest
from agentcy.fetch import store, yf
from agentcy.fetch.yf import FetchFailed

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
