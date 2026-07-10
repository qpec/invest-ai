"""Durable outbox — ENQUEUE side (P6). Tech-arch §5.4/§1.3.

Enqueue is exactly-once by dedupe_key UNIQUE. A re-run finding an unsent (queued)
row for its key replaces the payload in place; a re-run after a SENT row must pass
an attempt-qualified key (jobs use runner.qualified_key). Jobs call enqueue inside
their render+archive transaction; only the daemon delivers.
"""
from __future__ import annotations

from datetime import timedelta

from agentcy import db
from agentcy.clock import Clock


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
