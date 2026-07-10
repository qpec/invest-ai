"""Sparse populator milestone notes (design 2026-07-10 section 7). Two derived transitions,
each enqueued at most once via a fixed dedupe_key (plan notes 6/7): starter-set-complete and
first-full-pass-complete. notice-class output -> lint's calm-register bans apply (no '!',
no red glyphs). No nightly spam.

Review fix M1: the coverage predicate is FETCH coverage, not gradability, so the count is
worded "N names CACHED", never "gradable" — a cached name can still grade INSUFFICIENT if
the pinned rows (EBIT / Working Capital / ...) are absent within those cached periods."""
from __future__ import annotations

from agentcy import db, populate
from agentcy.render.contexts import RenderedOutput
from agentcy.tg import outbox

_STARTER_KEY = "populate:milestone:starter"
_FULL_PASS_KEY = "populate:milestone:full_pass"


def render_starter_note(*, cached: int) -> RenderedOutput:
    """One-liner: the starter set is cached (design 7; M1 wording — cached, not gradable)."""
    body = (f"Populator: starter set ready - {cached} names now cached. "
            f"Run `agentcy scout run grade` to see the first ranked picks.")
    return RenderedOutput(telegram_html=body, markdown=body, output_class="notice")


def render_full_pass_note(*, cached: int, skipped: int) -> RenderedOutput:
    """One-liner: the whole universe has been attempted at least once (design 7; M1 wording)."""
    body = (f"Populator: universe cached - {cached} names cached, "
            f"{skipped} skipped (delisted or data-thin). First full pass complete.")
    return RenderedOutput(telegram_html=body, markdown=body, output_class="notice")


def _starter_complete(conn, ranked, *, starter_size, as_of) -> bool:
    starter = ranked[:starter_size]
    return bool(starter) and all(populate.is_cached(conn, t, as_of=as_of) for t in starter)


def _full_pass_complete(conn, ranked) -> bool:
    latest = db.fetch_universe_fetch_latest(conn)
    return bool(ranked) and all(t in latest for t in ranked)


def _cached_count(conn, ranked, *, as_of) -> int:
    return sum(1 for t in ranked if populate.is_cached(conn, t, as_of=as_of))


def _already_delivered(conn, key) -> bool:
    """True once this milestone's fixed dedupe_key row has left the queue (status 'sent' or
    'collapsed') - the terminal states where `enqueue` would raise ValueError and the recompute
    is thrown away. A single indexed lookup that lets `maybe_emit_milestones` skip the whole
    detector branch on every night after delivery (no nightly full-universe DB walk)."""
    row = db.fetch_outbox_by_key(conn, key)
    return row is not None and row["status"] != "queued"


def _enqueue_once(conn, key, rendered, *, run_id, clock) -> None:
    """Enqueue idempotently: a queued row supersedes in place; a SENT row raises ValueError
    (caught) so a re-fire after delivery never re-notifies (plan note 7)."""
    from agentcy.render import lint
    linted, _ = lint.lint_or_fallback(rendered)
    try:
        outbox.enqueue(conn, dedupe_key=key, kind="notice",
                       payload_html=linted.telegram_html, run_id=run_id, clock=clock)
    except ValueError:
        pass  # already sent under this key - no re-notify


def maybe_emit_milestones(conn, ranked, *, starter_size, run_id, as_of, clock) -> None:
    """Enqueue the starter and/or first-full-pass note when the derived transition holds;
    each fires at most once (fixed dedupe_key). Called at the tail of every populate run.

    Once a milestone is delivered its key is skipped by a single indexed lookup, so the
    expensive coverage detectors (full-universe `is_cached` walks) never re-run nightly for
    a note that would only be discarded."""
    if (not _already_delivered(conn, _STARTER_KEY)
            and _starter_complete(conn, ranked, starter_size=starter_size, as_of=as_of)):
        _enqueue_once(conn, _STARTER_KEY,
                      render_starter_note(cached=_cached_count(conn, ranked, as_of=as_of)),
                      run_id=run_id, clock=clock)
    if (not _already_delivered(conn, _FULL_PASS_KEY)
            and _full_pass_complete(conn, ranked)):
        cached = _cached_count(conn, ranked, as_of=as_of)
        _enqueue_once(conn, _FULL_PASS_KEY,
                      render_full_pass_note(cached=cached, skipped=len(ranked) - cached),
                      run_id=run_id, clock=clock)
