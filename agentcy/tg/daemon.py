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


def _handle_callback(conn, cq, *, client, clock, owner_chat_id) -> None:
    # Filled in P7.9.
    client.answer_callback_query(cq.get("id"))


def _handle_freetext(conn, message, text, *, client, clock, owner_chat_id) -> None:
    # Filled in P7.10.
    pass
