"""Durable outbox — ENQUEUE side (P6). Tech-arch §5.4/§1.3.

Enqueue is exactly-once by dedupe_key UNIQUE. A re-run finding an unsent (queued)
row for its key replaces the payload in place; a re-run after a SENT row must pass
an attempt-qualified key (jobs use runner.qualified_key). Jobs call enqueue inside
their render+archive transaction; only the daemon delivers.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from agentcy import db
from agentcy.clock import Clock
from agentcy.tg.client import TelegramError, TelegramRetryAfter


def scheduled_key(run_type: str, scheduled_for: str, section: str, *, attempt: int | None = None) -> str:
    """'{run_type}:{scheduled_for}:{section}' (+'#a{n}' attempt qualifier for post-sent revisions)."""
    base = f"{run_type}:{scheduled_for}:{section}"
    return f"{base}#a{attempt}" if attempt is not None else base


def event_key(yf_ticker: str, detected_at: str, section: str) -> str:
    """'event:{ticker}:{detected_at}:{section}'."""
    return f"event:{yf_ticker}:{detected_at}:{section}"


def alert_key(alert_id: int) -> str:
    """'alert:{alert_id}' — alerts retry until delivered, no dead-letter state."""
    return f"alert:{alert_id}"


def enqueue(conn, *, dedupe_key: str, kind: str, payload_html: str, document_path: str | None = None,
            reply_markup_json: str | None = None, ask_ref: str | None = None,
            artifact_ref: int | None = None, run_id: int | None = None, clock: Clock) -> int:
    """Insert or supersede-in-place per §5.4; raises ValueError on a sent/collapsed key."""
    existing = db.fetch_outbox_by_key(conn, dedupe_key)
    if existing is not None:
        if existing["status"] == "queued":
            db.supersede_outbox_payload(conn, existing["outbox_id"], payload_html=payload_html,
                                        document_path=document_path, reply_markup_json=reply_markup_json)
            return existing["outbox_id"]
        raise ValueError(
            f"dedupe_key {dedupe_key!r} already {existing['status']}; "
            "pass an attempt-qualified key (tech-arch §5.4)")
    return db.append_outbox(
        conn, dedupe_key=dedupe_key, kind=kind, created_at=db.to_iso(clock.now()),
        run_id=run_id, artifact_ref=artifact_ref, ask_ref=ask_ref,
        payload_html=payload_html, document_path=document_path,
        reply_markup_json=reply_markup_json)

# --- P7 (daemon) drain/backoff/collapse land below this marker ---

_BACKOFF = [
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(minutes=30),
]
_HOURLY = timedelta(hours=1)


def next_backoff(attempts: int) -> timedelta:
    """30s, 2m, 10m, 30m, then hourly (§5.4)."""
    if attempts < len(_BACKOFF):
        return _BACKOFF[attempts]
    return _HOURLY


def collapse_stale_letters(conn, *, as_of: datetime) -> int:
    """Mark superseded queued daily letters 'collapsed' (newest stays queued); returns count.

    The archive keeps all letters (report rows are untouched) — only delivery is collapsed
    so the owner does not get a backlog of stale 'no action needed' letters (§5.3/§1.3).
    """
    dailies = [r for r in db.fetch_outbox_queued(conn) if r["kind"] == "daily"]
    if len(dailies) <= 1:
        return 0
    # fetch_outbox_queued is FIFO by created_at; the last one is newest.
    stale = dailies[:-1]
    for r in stale:
        db.update_outbox_state(conn, r["outbox_id"], status="collapsed")
    return len(stale)


def drain(conn, client, *, clock: Clock, chat_id: int, sleep=None) -> dict:
    """FIFO by created_at, alerts first on flush; collapse stale daily letters; >=1s pacing;
    honor retry_after; mark sent ONLY on ok:true with message_id stored; backoff ladder;
    alerts have no dead-letter (§5.3/§5.4). Delivery is at-least-once.

    ``chat_id`` (required, single-owner) and ``sleep`` (test seam) are additive keyword-only
    args beyond contracts §3.20 (R10); the positional/``clock`` shape is preserved.
    """
    import time as _time
    if sleep is None:
        sleep = _time.sleep

    collapsed = collapse_stale_letters(conn, as_of=clock.now())

    rows = db.fetch_outbox_queued(conn)  # FIFO by created_at (contract)
    now = clock.now()

    def _due(r):
        if r["next_attempt_at"] is None:
            return True
        return db.from_iso(r["next_attempt_at"]) <= now

    # alerts first, otherwise stable FIFO (sorted() preserves the fetch order within a class).
    ordered = sorted((r for r in rows if _due(r)),
                     key=lambda r: (0 if r["kind"] == "alert" else 1,))

    sent = 0
    retry_after = None
    first = True
    for r in ordered:
        if not first:
            sleep(1.0)  # >=1s pacing (§5.5)
        first = False
        try:
            reply_markup = json.loads(r["reply_markup_json"]) if r["reply_markup_json"] else None
            if r["document_path"]:
                content = Path(r["document_path"]).read_bytes()
                filename = os.path.basename(r["document_path"])
                msg = client.send_document(chat_id, filename, content, caption=r["payload_html"])
            else:
                msg = client.send_message(chat_id, r["payload_html"], reply_markup=reply_markup)
        except TelegramRetryAfter as e:
            retry_after = e.retry_after
            deferred = db.to_iso(clock.now() + timedelta(seconds=e.retry_after))
            db.update_outbox_state(conn, r["outbox_id"], next_attempt_at=deferred)
            break  # never hammer — stop this batch
        except (TelegramError, OSError):
            attempts = r["attempts"] + 1
            nxt = db.to_iso(clock.now() + next_backoff(attempts))
            db.update_outbox_state(conn, r["outbox_id"], attempts=attempts, next_attempt_at=nxt)
            continue  # alert stays queued (no dead-letter); letters retry too
        db.update_outbox_state(conn, r["outbox_id"], status="sent",
                               tg_message_id=msg.get("message_id"))
        sent += 1
    return {"sent": sent, "collapsed": collapsed, "retry_after": retry_after}
