"""Sparse populator milestones (populator design 7). Derived transitions, notice-class
render (golden), idempotent outbox enqueue. No nightly spam.

Review fix M1: the coverage predicate is FETCH coverage, not gradability, so the notes
word the count "N names CACHED", never "gradable" (a cached name can still grade
INSUFFICIENT). The render functions and the golden text reflect that wording."""
from datetime import datetime, timezone

import pandas as pd

from agentcy import db
from agentcy.clock import FixedClock
from agentcy.fetch import store
from agentcy.render import populate as rp

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
CLOCK = FixedClock(AS_OF)


def _cache(conn, sym):
    cols = pd.to_datetime(["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])
    for stype, rows in (("income", {"Total Revenue": 1e11, "EBITDA": 4e10}),
                        ("balance", {"Total Debt": 5e10, "Cash And Cash Equivalents": 8e10}),
                        ("cashflow", {"Operating Cash Flow": 4e10, "Capital Expenditure": -5e9})):
        frame = pd.DataFrame({c: rows for c in cols})
        store.store_statements(conn, sym, {stype: frame}, run_id=None,
                               fetched_at="2026-07-07T00:00:00Z")
    store.store_shares(conn, sym, pd.Series([7.4e9], index=pd.to_datetime(["2026-07-01"])),
                       fetched_at="2026-07-07T00:00:00Z")
    frame = pd.DataFrame({"close": [500.0], "adj_close": [500.0], "dividend": [0.0],
                          "currency": ["USD"]}, index=pd.to_datetime(["2026-07-07"]))
    store.store_price_bars(conn, sym, frame, run_id=None, fetched_at="2026-07-07T00:00:00Z")


def test_render_starter_note_golden(golden):
    out = rp.render_starter_note(cached=2)
    assert out.output_class == "notice"
    # M1: the count is a CACHED count, never worded "gradable".
    assert "cached" in out.markdown.lower()
    assert "gradable" not in out.markdown.lower()
    golden("populate_starter.md", out.markdown)


def test_render_full_pass_note_golden(golden):
    out = rp.render_full_pass_note(cached=2, skipped=1)
    assert "gradable" not in out.markdown.lower()
    golden("populate_full_pass.md", out.markdown)


def test_starter_milestone_enqueues_once(tmp_db):
    ranked = ["MSFT", "VEEV"]
    _cache(tmp_db, "MSFT")
    _cache(tmp_db, "VEEV")
    rp.maybe_emit_milestones(tmp_db, ranked, starter_size=2, run_id=None,
                             as_of=AS_OF, clock=CLOCK)
    tmp_db.commit()
    queued = [r for r in db.fetch_outbox_queued(tmp_db) if r["kind"] == "notice"]
    assert len(queued) == 1
    assert "starter set ready" in queued[0]["payload_html"].lower()
    # a second run does not enqueue a duplicate (idempotent by fixed dedupe_key)
    rp.maybe_emit_milestones(tmp_db, ranked, starter_size=2, run_id=None,
                             as_of=AS_OF, clock=CLOCK)
    tmp_db.commit()
    assert len([r for r in db.fetch_outbox_queued(tmp_db) if r["kind"] == "notice"]) == 1


def test_no_milestone_before_starter_complete(tmp_db):
    ranked = ["MSFT", "VEEV"]
    _cache(tmp_db, "MSFT")  # only 1 of 2 cached
    rp.maybe_emit_milestones(tmp_db, ranked, starter_size=2, run_id=None,
                             as_of=AS_OF, clock=CLOCK)
    tmp_db.commit()
    assert [r for r in db.fetch_outbox_queued(tmp_db) if r["kind"] == "notice"] == []


def test_milestone_refire_after_delivery_never_raises(tmp_db):
    """Plan note 7: once the fixed-dedupe-key note is SENT, a re-fire on a later night must
    swallow the outbox ValueError (no re-notify, no crash)."""
    ranked = ["MSFT", "VEEV"]
    _cache(tmp_db, "MSFT")
    _cache(tmp_db, "VEEV")
    rp.maybe_emit_milestones(tmp_db, ranked, starter_size=2, run_id=None,
                             as_of=AS_OF, clock=CLOCK)
    tmp_db.commit()
    row = db.fetch_outbox_by_key(tmp_db, "populate:milestone:starter")
    db.update_outbox_state(tmp_db, row["outbox_id"], status="sent", tg_message_id=1)
    tmp_db.commit()
    # a subsequent night re-fires the same milestone; the SENT key must not raise.
    rp.maybe_emit_milestones(tmp_db, ranked, starter_size=2, run_id=None,
                             as_of=AS_OF, clock=CLOCK)
    tmp_db.commit()
    # no new queued notice appeared (the sent row is untouched).
    assert [r for r in db.fetch_outbox_queued(tmp_db) if r["kind"] == "notice"] == []
