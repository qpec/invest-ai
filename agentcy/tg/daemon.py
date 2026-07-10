"""Telegram long-poll daemon (tech-arch §5.2/§5.3/§5.5). Synchronous, single-threaded,
watchdog-budgeted. Owner lock at the top of handle(). last_update_id persisted in the
same transaction as handle()'s writes (P7.13)."""
from __future__ import annotations

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
        _handle_message(conn, update["message"], client=client, clock=clock,
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


def _handle_command(conn, message, text, *, client, clock, owner_chat_id) -> None:
    cmd = text.split()[0].lstrip("/").split("@")[0].lower()
    if cmd == "help":
        client.send_message(owner_chat_id, esc(HELP_TEXT))
    # remaining commands land in P7.11.


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


def _handle_freetext(conn, message, text, *, client, clock, owner_chat_id) -> None:
    # Filled in P7.10.
    pass
