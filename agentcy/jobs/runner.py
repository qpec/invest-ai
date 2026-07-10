"""Job runner — the run_type-scoped due-run sweep (tech-arch §1.3, review-fixed).

Each job's sweep re-runs ONLY its own run_type's due keys (the quarterly job, and
therefore the benchmark, can never be pulled into another process). A per-run_type
flock held for the run makes 'currently running' mechanically distinct from
'crashed'; started-but-unfinished keys are re-runnable only when unlocked AND
started_at is older than the unit's TimeoutStartSec (JOB_TIMEOUT mirrors 30min).
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from agentcy import db, runlog
from agentcy.clock import Clock
from agentcy.render import common as render_common, contexts, lint
from agentcy.render import daily as render_daily_mod
from agentcy.tg import outbox

JOB_TIMEOUT = timedelta(minutes=30)  # mirrors TimeoutStartSec=30min (tech-arch §1.2)

# Where each run_type's degraded honesty letter lands: (section, outbox kind).
PRIMARY_SECTION = {
    "daily": ("letter", "daily"),
    "weekly": ("msg1", "weekly_msg"),
    "quarterly": ("summary", "quarterly_msg"),
    "event": ("report", "event"),
    "backup": ("notice", "notice"),
}


def qualified_key(conn, base: str) -> str:
    """base while free/queued (supersession applies); '#a{n}' revision key once sent (§5.4)."""
    row = db.fetch_outbox_by_key(conn, base)
    if row is None or row["status"] == "queued":
        return base
    n = 2
    while True:
        k = f"{base}#a{n}"
        row = db.fetch_outbox_by_key(conn, k)
        if row is None or row["status"] == "queued":
            return k
        n += 1


def sweep_and_run(conn, run_type: str, job_fn, *, clock: Clock, state_dir: Path,
                  timeout: timedelta = JOB_TIMEOUT) -> int:
    """For every due key of run_type absent or crashed (per runlog.sweepable), run job_fn
    under the per-type lock. Finished keys exit 0. The newest due key is on-time; every
    other swept key is marked late. Keys run newest-first so a global data outage ships
    the degraded honesty letter under TODAY's primary key (the one the owner is waiting on,
    P6.3) rather than an old catch-up key, before re-raising. Plan note: sweepable is
    computed BEFORE taking our own lock (flock is per-open-file-description — probing a
    lock we hold would misread), then each key is re-checked with is_done inside the lock
    (a 'failed' key is NOT done — it is re-claimed and re-run, FIX.3)."""
    keys = runlog.sweepable(conn, run_type, as_of=clock.now(), timeout=timeout, state_dir=state_dir)
    if not keys:
        return 0
    newest = max(keys)
    with runlog.run_lock(state_dir, run_type):
        for key in sorted(keys, reverse=True):
            if runlog.is_done(conn, run_type, key):
                continue
            handle = runlog.start(conn, run_type, key, clock=clock, late=(key != newest))
            conn.commit()
            try:
                status, outputs = job_fn(conn, handle, clock=clock, state_dir=state_dir)
            except Exception as exc:                      # degraded-letter guard: P6.3
                _on_job_exception(conn, handle, clock=clock, exc=exc)
                raise                                     # OnFailure= fires AND the letter shipped
            runlog.finish(conn, handle.run_id, status=status, outputs=outputs, clock=clock)
            conn.commit()
    return 0


def enqueue_rendered(conn, r, *, base_key: str, kind: str, run_id: int | None, clock: Clock,
                     artifact_ref: int | None = None, document_path: str | None = None) -> list:
    """Lint (fail-closed, §8) then enqueue under the supersession-aware key; returns violations."""
    linted, violations = lint.lint_or_fallback(r)
    outbox.enqueue(conn, dedupe_key=qualified_key(conn, base_key), kind=kind,
                   payload_html=linted.telegram_html, document_path=document_path,
                   reply_markup_json=linted.reply_markup_json, ask_ref=linted.ask_id,
                   artifact_ref=artifact_ref, run_id=run_id, clock=clock)
    return violations


def honesty_letter(conn, handle, *, clock: Clock) -> None:
    """The D.1 honesty letter (§1.3): 'Data sources unavailable since {t}; last known state;
    no checks performed. Nothing is wrong; I just can't see.' Written to the outbox and
    COMMITTED before the exception propagates, under the run's primary section key so a
    successful re-run supersedes it (queued) or revision-rows it (sent)."""
    since = handle.scheduled_for
    ctx = contexts.DailyContext(
        kind="total_failure", as_of=clock.now(), header=None,
        verdict_line=(f"Data sources unavailable since {since}; last known state; "
                      f"no checks performed. {render_common.DEGRADED_LINE}"),
        opportunities=(), more_opportunities=0, events_line=None,
        data_lines=(f"run {handle.run_type}:{handle.scheduled_for} failed before completing",),
        open_loops=(), open_items_count=0, generated_at=clock.now(),
        late_banner=None,
    )
    r = render_daily_mod.render_daily(ctx)
    section, kind = PRIMARY_SECTION[handle.run_type]
    base = outbox.scheduled_key(handle.run_type, handle.scheduled_for, section)
    enqueue_rendered(conn, r, base_key=base, kind=kind, run_id=handle.run_id, clock=clock)
    conn.commit()


def _on_job_exception(conn, handle, *, clock, exc) -> None:
    """Ship the degraded honesty letter, then finish the run as 'failed'. The finish stamp
    keeps /status honest (build_status_context reads the last FINISHED run's status), while
    runlog.sweepable/start still re-claim a 'failed' key on a later sweep so the REAL letter
    is re-run — never silently lost (FIX.3, NFR1/§1.3). The letter must never mask the
    original failure — OnFailure= still fires (we re-raise upstream)."""
    try:
        honesty_letter(conn, handle, clock=clock)
    except Exception:
        pass  # the letter must never mask the original failure; OnFailure still fires
    runlog.finish(conn, handle.run_id, status="failed", outputs={"error": repr(exc)}, clock=clock)
    conn.commit()
