"""P7.13: sync loop — watchdog pings, batch cap, offset persisted with handle() writes,
replay idempotence (§5.2), and the report-only startup sweep (R7)."""
from __future__ import annotations

from agentcy import db
from agentcy.asks import mint
from agentcy.tg import daemon


class _LoopClient:
    def __init__(self, updates):
        self._updates = updates
        self.sent = []
        self.answered = []
        self.edited = []
    def get_updates(self, *, offset, timeout=25, limit=25):
        batch, self._updates = self._updates[:limit], self._updates[limit:]
        # only return updates whose id >= offset (mimic Telegram ack semantics)
        return [u for u in batch if u["update_id"] >= offset]
    def send_message(self, chat_id, html, *, reply_markup=None):
        self.sent.append(html); return {"message_id": 1}
    def answer_callback_query(self, cbq_id, *, text=None):
        self.answered.append(text)
    def edit_message_text(self, *a, **k): return {"message_id": 1}
    def send_chat_action(self, *a, **k): pass


def test_serve_once_persists_offset_and_pings_watchdog(tmp_db, fixed_clock):
    pings = []
    client = _LoopClient([{"update_id": 10, "message": {"chat": {"id": 555}, "text": "/help"}}])
    daemon.serve_once(tmp_db, client, clock=fixed_clock, owner_chat_id=555,
                      notify=pings.append)
    assert db.fetch_bot_state(tmp_db)["last_update_id"] == 10
    assert pings.count("WATCHDOG=1") >= 2  # top + between handles


def test_replayed_answered_ask_is_harmless(tmp_db, fixed_clock):
    ask = mint(tmp_db, kind="Q", prompt="x", options=["yes", "no"], clock=fixed_clock)
    db.update_ask_state(tmp_db, ask.ask_id, status="open", tg_message_id=9)
    cb = {"update_id": 20, "callback_query": {"id": "CB", "from": {"id": 555},
          "message": {"chat": {"id": 555}, "message_id": 9}, "data": f"trig:yes:{ask.ask_id}"}}
    client = _LoopClient([cb])
    daemon.serve_once(tmp_db, client, clock=fixed_clock, owner_chat_id=555, notify=lambda _s: None)
    assert db.fetch_ask(tmp_db, ask.ask_id)["status"] == "answered"
    # replay the SAME update (crash-in-window): already answered -> no crash, ack says recorded
    client2 = _LoopClient([{**cb, "update_id": 20}])
    # force offset back so the update is re-seen
    db.update_bot_state(tmp_db, last_update_id=19)
    daemon.serve_once(tmp_db, client2, clock=fixed_clock, owner_chat_id=555, notify=lambda _s: None)
    assert any("recorded" in (t or "").lower() for t in client2.answered)


def test_batch_is_capped_at_25(tmp_db, fixed_clock):
    ups = [{"update_id": i, "message": {"chat": {"id": 555}, "text": "/help"}} for i in range(1, 40)]
    client = _LoopClient(ups)
    daemon.serve_once(tmp_db, client, clock=fixed_clock, owner_chat_id=555, notify=lambda _s: None)
    # at most 25 handled this iteration; offset advanced to the 25th
    assert db.fetch_bot_state(tmp_db)["last_update_id"] == 25


def test_startup_sweep_reports_only_never_runs_a_job(tmp_db, fixed_clock):
    """R7: the daemon detects and reports missing due keys via an outbox notice —
    it NEVER inserts a run_log row and NEVER executes a job (tech-arch §1.3)."""
    from agentcy import runlog
    missing = runlog.report_missing(tmp_db, as_of=fixed_clock.now())
    assert missing  # the fixture db has no finished runs, so keys are due
    daemon._startup_sweep(tmp_db, clock=fixed_clock)
    # not one job was executed: the run_log stays empty
    assert tmp_db.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 0
    # every missing key was reported as a durable notice for the owner
    notices = [r for r in db.fetch_outbox_queued(tmp_db) if r["kind"] == "notice"]
    assert len(notices) == len(missing)
    # idempotent: a second sweep supersedes in place, does not duplicate
    daemon._startup_sweep(tmp_db, clock=fixed_clock)
    notices = [r for r in db.fetch_outbox_queued(tmp_db) if r["kind"] == "notice"]
    assert len(notices) == len(missing)
    assert tmp_db.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 0
