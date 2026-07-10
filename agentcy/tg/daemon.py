"""Telegram long-poll daemon (tech-arch §5.2/§5.3/§5.5). Synchronous, single-threaded,
watchdog-budgeted. Owner lock at the top of handle(). last_update_id persisted in the
same transaction as handle()'s writes (P7.13)."""
from __future__ import annotations

from agentcy import db
from agentcy.clock import Clock
from agentcy.render.common import esc

HELP_TEXT = (
    "stock-agentcy commands:\n"
    "/status - the calm state now\n"
    "/pause - declare an absence window\n"
    "/resume - end an absence window\n"
    "/event - owner-injected event check\n"
    "/snapshot - ingest a portfolio export\n"
    "/help - this reference\n\n"
    "I advise and monitor. I never trade. "
    "I only ever ask you things you pre-committed to answer."
)

START_TEXT = (
    "stock-agentcy is online, locked to this chat.\n\n"
    "I monitor the theses behind your holdings and tell you when the reason\n"
    "you bought something no longer holds. I advise; I never trade.\n\n"
    "Commands: /status  /pause  /resume  /event  /snapshot  /help"
)

PAUSE_TEXT = (
    "Pause mode. Deadlines and skip counters freeze. Alerts still arrive;\n"
    "weekly reviews still run. Daily letters: your choice below.\n\nHow long?"
)
_PAUSE_KEYBOARD = {"inline_keyboard": [
    [{"text": "Until I resume (open-ended)", "callback_data": "pause:set:open"}],
    [{"text": "1 week", "callback_data": "pause:set:7d"}],
    [{"text": "2 weeks", "callback_data": "pause:set:14d"}],
    [{"text": "Custom end date…", "callback_data": "pause:set:custom"}],
]}

SNAPSHOT_TEXT = (
    "Add a portfolio snapshot. Send a file or paste positions — I'll\n"
    "reconcile it against what I last saw and ask about anything I can't explain."
)
_SNAPSHOT_KEYBOARD = {"inline_keyboard": [
    [{"text": "Upload export file (CSV)", "callback_data": "snap:mode:file"}],
    [{"text": "Paste positions as text", "callback_data": "snap:mode:text"}],
    [{"text": "Cancel", "callback_data": "snap:cancel"}],
]}


def _command_menu() -> list[dict]:
    """The seven-command surface handed to set_my_commands at start (§1, R10)."""
    return [
        {"command": "start", "description": "orientation"},
        {"command": "status", "description": "the calm state now"},
        {"command": "pause", "description": "declare an absence window"},
        {"command": "resume", "description": "end an absence window"},
        {"command": "event", "description": "owner-injected event check"},
        {"command": "snapshot", "description": "ingest a portfolio export"},
        {"command": "help", "description": "quick reference"},
    ]


def _acting_chat_id(update: dict) -> int | None:
    if "message" in update:
        return update["message"].get("chat", {}).get("id")
    if "callback_query" in update:
        cq = update["callback_query"]
        return cq.get("message", {}).get("chat", {}).get("id") or cq.get("from", {}).get("id")
    if "my_chat_member" in update:
        return update["my_chat_member"].get("chat", {}).get("id")
    if "edited_message" in update:
        return update["edited_message"].get("chat", {}).get("id")
    return None


def handle(conn, update: dict, *, client, clock: Clock, owner_chat_id: int) -> None:
    """Process ONE update. Owner lock is the very first step (§5.3). Any writes here and the
    caller's last_update_id persist land in ONE transaction (P7.13)."""
    chat_id = _acting_chat_id(update)
    if chat_id != owner_chat_id:
        # Dropped silently — a reply confirms the bot exists and is worth attacking (§5.1).
        return

    if "message" in update:
        message = update["message"]
        if "document" in message:
            _handle_document(conn, message, client=client, clock=clock,
                             owner_chat_id=owner_chat_id)
        else:
            _handle_message(conn, message, client=client, clock=clock,
                            owner_chat_id=owner_chat_id)
    elif "callback_query" in update:
        _handle_callback(conn, update["callback_query"], client=client, clock=clock,
                         owner_chat_id=owner_chat_id)
    # my_chat_member / other kinds: no-op in this phase (outbox keeps queuing).


def _handle_message(conn, message: dict, *, client, clock, owner_chat_id) -> None:
    text = (message.get("text") or "").strip()
    if text.startswith("/"):
        _handle_command(conn, message, text, client=client, clock=clock, owner_chat_id=owner_chat_id)
        return
    _handle_freetext(conn, message, text, client=client, clock=clock, owner_chat_id=owner_chat_id)


# --- /snapshot document ingestion (state-scoped to snap:mode:file, §1.5) -------

_SNAP_FILE_OPT = "snap:file"


def _open_snap_file_ask(conn):
    """The single open N-ask that records a pending file upload, or None."""
    from agentcy import asks
    for a in asks.open_asks(conn, kind="N"):
        if _SNAP_FILE_OPT in a.options:
            return a
    return None


def _handle_document(conn, message, *, client, clock, owner_chat_id) -> None:
    """Ingest a document ONLY when a snap:file ask is open; a cold file is redirected,
    never ingested (a stray upload must not become portfolio truth, §1.5/§4)."""
    pending = _open_snap_file_ask(conn)
    if pending is None:
        client.send_message(owner_chat_id, esc(
            "I only ingest a file right after you choose 'Upload export file' in /snapshot. "
            "Send /snapshot to start."))
        return
    from agentcy import asks, mirror
    doc = message["document"]
    client.send_chat_action(owner_chat_id, "typing")  # >1s work ahead (§5.5)
    info = client.get_file(doc["file_id"])
    raw = client.download_file(info["file_path"])
    snap = mirror.parse_etoro_csv(raw.decode("utf-8"))
    _snap_id, deltas = mirror.ingest_snapshot(conn, snap, clock=clock)
    asks.answer(conn, pending.ask_id, text="file ingested", clock=clock)
    # Reconciliation R-asks (§3.4) are minted by ingest's domain/jobs caller; here we
    # only count and point to /status.
    if deltas:
        client.send_message(owner_chat_id, esc(
            f"Snapshot accepted. {len(deltas)} items need reconciliation — see /status."))
    else:
        client.send_message(owner_chat_id, esc("Snapshot accepted. Everything reconciles."))


def _handle_command(conn, message, text, *, client, clock, owner_chat_id) -> None:
    cmd = text.split()[0].lstrip("/").split("@")[0].lower()
    if cmd == "start":
        client.send_message(owner_chat_id, esc(START_TEXT))
    elif cmd == "status":
        client.send_message(owner_chat_id, _status_card(conn, clock=clock))
    elif cmd == "pause":
        client.send_message(owner_chat_id, esc(PAUSE_TEXT), reply_markup=_PAUSE_KEYBOARD)
    elif cmd == "resume":
        client.send_message(owner_chat_id, _resume_summary(conn, clock=clock))
    elif cmd == "event":
        client.send_message(
            owner_chat_id,
            esc("Which holding had an event? (earnings, filing, management change)"),
            reply_markup=_event_picker(conn))
    elif cmd == "snapshot":
        client.send_message(owner_chat_id, esc(SNAPSHOT_TEXT), reply_markup=_SNAPSHOT_KEYBOARD)
    else:  # help + any unknown slash command land on the quick reference (§1)
        client.send_message(owner_chat_id, esc(HELP_TEXT))


def _status_card(conn, *, clock) -> str:
    """Render the G.1 status card from last RunLog state — NEVER runs checks (§1.2, R2)."""
    from agentcy.render.daily import build_status_context, render_status
    ctx = build_status_context(conn, as_of=clock.now())
    return render_status(ctx).telegram_html


def _resume_summary(conn, *, clock) -> str:
    """End the absence window via the shared domain writer (R3); report the flip."""
    from agentcy import absence
    absence.resume(conn, reason="owner /resume", clock=clock)
    return esc("Resumed. Frozen deadlines and skip counters are live again.")


def _event_picker(conn) -> dict:
    """Ticker keyboard for /event: held positions (live thesis id when known) + a new-position row."""
    from agentcy import mirror, register
    buttons = []
    for p in mirror.advice_positions(conn)[:8]:
        tid = register.live_thesis_for(conn, p.symbol) or p.symbol
        buttons.append([{"text": p.symbol, "callback_data": f"evt:pick:{tid}"}])
    buttons.append([{"text": "It's a ticker not shown / new position",
                     "callback_data": "evt:pick:new"}])
    return {"inline_keyboard": buttons}


def _callback_choice(action: str, parts: list[str]) -> str | None:
    """The enumerated option the tap selects. Verb-as-choice (trig:yes/no/cant, alert:confirm/refute)
    or trailing value segment(s) (recon:pick:R77:close, reaff:set:F19:conviction:high)."""
    if len(parts) > 3:
        return ":".join(parts[3:])   # value-carrying grammar
    return action                    # verb IS the choice


def _parse_callback(data: str) -> tuple[str, str, str | None, str | None]:
    """(domain, action, ask_id, choice). Grammar: <domain>:<action>:<ask_id>[:<value>...] (§3.1)."""
    parts = data.split(":")
    domain = parts[0] if parts else ""
    action = parts[1] if len(parts) > 1 else ""
    ask_id = parts[2] if len(parts) > 2 else None
    choice = _callback_choice(action, parts)
    return domain, action, ask_id, choice


def _handle_callback(conn, cq, *, client, clock, owner_chat_id) -> None:
    """Validate against the ask row, always ack (§5.5), edit + strip keyboard on resolve (§3.10).
    Per-kind consequences are the domain layer's side effect keyed off AnswerOutcome.consequence;
    this routes and edits only — a phone never mutates a trigger threshold (revise → desk, §5.5)."""
    from agentcy import asks

    cbq_id = cq.get("id")
    data = cq.get("data") or ""
    msg_id = cq.get("message", {}).get("message_id")

    # /snapshot mode taps carry no ask_id — they mint state or cancel (§1.5), so they
    # must be handled before the generic ask-validation path below.
    if data == "snap:mode:file":
        asks.mint(conn, kind="N", prompt="Send the CSV export now",
                  options=[_SNAP_FILE_OPT], expects_freetext=True, clock=clock)
        client.answer_callback_query(cbq_id, text="Ready")
        client.send_message(owner_chat_id, esc("Send the CSV export as a document now."))
        return
    if data == "snap:cancel":
        client.answer_callback_query(cbq_id, text="Cancelled")
        return

    _domain, _action, ask_id, choice = _parse_callback(data)

    if not ask_id or asks.get(conn, ask_id) is None:
        client.answer_callback_query(cbq_id, text="This choice is no longer available")
        return

    outcome = asks.answer(conn, ask_id, choice=choice, clock=clock, tg_message_id=msg_id)
    if outcome.already_recorded:
        client.answer_callback_query(cbq_id, text="Already recorded")
        return
    if not outcome.accepted:
        client.answer_callback_query(cbq_id, text="This choice is no longer available")
        return

    client.answer_callback_query(cbq_id, text="Recorded")
    # Resolution edit: show the recorded choice, strip the keyboard (§3.10).
    if msg_id is not None:
        try:
            client.edit_message_text(
                owner_chat_id, msg_id, esc(f"Recorded: {choice} ({ask_id})."), reply_markup=None)
        except Exception:
            pass  # a failed edit never blocks the recorded answer (SQLite is truth)


GENTLE_REDIRECT = (
    "I only act on the commands and on questions I've asked you. "
    "Nothing is waiting right now. /status shows the current picture."
)


def _reply_to_ask_id(message: dict) -> str | None:
    """Extract the trailing [ask_id] token embedded in a ForceReply prompt (tg-spec §4.1)."""
    rt = message.get("reply_to_message") or {}
    text = rt.get("text") or ""
    if text.endswith("]") and "[" in text:
        return text[text.rindex("[") + 1 : -1] or None
    return None


def _short_label(ask) -> str:
    return (ask.prompt or ask.ask_id)[:32]


def _handle_freetext(conn, message, text, *, client, clock, owner_chat_id) -> None:
    """Attribute inbound plain text to an open free-text ask; never guess (tg-spec §4)."""
    from agentcy import asks

    reply_to = _reply_to_ask_id(message)
    resolved = asks.resolve_freetext(conn, reply_to_ask_id=reply_to)

    if resolved is None:
        # No open ask — never parsed, never stored; gently redirect (§4).
        client.send_message(owner_chat_id, esc(GENTLE_REDIRECT))
        return

    if isinstance(resolved, list):
        # Several open — the bot CANNOT guess (§4). Offer a bind keyboard.
        buttons = [[{"text": _short_label(a), "callback_data": f"sys:bind:{a.ask_id}"}]
                   for a in resolved]
        client.send_message(
            owner_chat_id,
            esc("More than one question is open. Which does this answer? "
                "Tap it, then send your reply again."),
            reply_markup={"inline_keyboard": buttons})
        return

    ask = resolved
    if not text.strip():
        asks.reprompt(conn, ask.ask_id, clock=clock)  # exactly one re-prompt (§3.6)
        client.send_message(
            owner_chat_id,
            esc(f"I didn't get a usable answer for {ask.ask_id}. "
                "One more try, or leave it and I'll record it as unanswered."))
        return

    asks.answer(conn, ask.ask_id, text=text, clock=clock)
    echo = text[:60] + ("…" if len(text) > 60 else "")
    client.send_message(owner_chat_id, esc(f"Recorded against {ask.ask_id}: '{echo}'"))


# --- sync loop, report-only startup sweep, entrypoint (§5.2/§1.3, R7) ----------

def _startup_sweep(conn, *, clock: Clock) -> None:
    """Report-only startup sweep (R7, tech-arch §1.3: the daemon detects and reports,
    never executes). Enqueue one durable 'notice' per missing due key; NEVER touch
    run_log, NEVER run a job. Idempotent — the 'health:{key}' dedupe supersedes in place
    across restarts so a lingering gap is not re-announced on every boot."""
    from agentcy import runlog
    from agentcy.tg import outbox
    for key in runlog.report_missing(conn, as_of=clock.now()):
        outbox.enqueue(
            conn, dedupe_key=f"health:{key}", kind="notice",
            payload_html=esc(
                f"Data-health notice: {key} was due but has not completed. "
                "I only detect and report — I never run a job for you."),
            clock=clock)
    conn.commit()


def serve_once(conn, client, *, clock, owner_chat_id, notify=None) -> None:
    """One loop iteration (§5.2). WATCHDOG at top, between sends (via drain hook), between handles.
    last_update_id persists in the SAME transaction as each handle()'s writes."""
    from agentcy.tg import outbox
    if notify is None:
        from agentcy import sdnotify
        notify = sdnotify.notify

    notify("WATCHDOG=1")

    # Deliver first so a busy inbound batch can never starve the outbox.
    try:
        outbox.drain(conn, client, clock=clock, chat_id=owner_chat_id,
                     sleep=lambda _s: notify("WATCHDOG=1"))
    except Exception:
        pass  # delivery failure never stops the loop; artifacts stay durable in SQLite

    state = db.fetch_bot_state(conn)
    offset = state["last_update_id"] + 1
    updates = client.get_updates(offset=offset, timeout=25, limit=25)

    for u in updates:
        with conn:  # ONE transaction: handle() writes + offset persist commit together (§5.2)
            handle(conn, u, client=client, clock=clock, owner_chat_id=owner_chat_id)
            db.update_bot_state(conn, last_update_id=u["update_id"])
        notify("WATCHDOG=1")


def run() -> None:
    """Entry point (agentcy bot / agentcy-bot.service). Reads env, never returns (§5.2/§5.3)."""
    import os

    from agentcy import sdnotify
    from agentcy.clock import SystemClock
    from agentcy.tg.client import TelegramClient

    token = os.environ["AGENTCY_BOT_TOKEN"]
    owner_chat_id = int(os.environ["AGENTCY_OWNER_CHAT_ID"])
    conn = db.open_db()
    db.migrate(conn)
    client = TelegramClient(token)
    client.set_my_commands(_command_menu())

    clock = SystemClock()
    _startup_sweep(conn, clock=clock)  # detect + report only (R7)
    sdnotify.ready()

    while True:
        serve_once(conn, client, clock=clock, owner_chat_id=owner_chat_id)
