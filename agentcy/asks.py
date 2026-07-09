"""agentcy/asks.py — D.5 first-class ask objects; state machine per tg-spec §3/§7."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from agentcy import db
from agentcy.clock import Clock, effective_deadline, is_paused

KINDS = frozenset({"A", "Q", "R", "F", "V", "N"})


@dataclass(frozen=True)
class Ask:
    ask_id: str
    kind: str
    prompt: str
    options: tuple[str, ...]
    expects_freetext: bool
    thesis_ref: str | None
    trigger_ref: int | None
    alert_ref: int | None
    deadline: datetime | None
    status: str
    answer: Mapping | None
    tg_message_id: int | None
    created_at: datetime


@dataclass(frozen=True)
class AnswerOutcome:
    ask: Ask
    accepted: bool
    already_recorded: bool
    consequence: str


def _row_to_ask(row) -> Ask:
    return Ask(
        ask_id=row["ask_id"], kind=row["kind"], prompt=row["prompt"],
        options=tuple(json.loads(row["options_json"])),
        expects_freetext=bool(row["expects_freetext"]),
        thesis_ref=row["thesis_ref"], trigger_ref=row["trigger_ref"], alert_ref=row["alert_ref"],
        deadline=db.from_iso(row["deadline"]) if row["deadline"] else None,
        status=row["status"],
        answer=json.loads(row["answer_json"]) if row["answer_json"] else None,
        tg_message_id=row["tg_message_id"],
        created_at=db.from_iso(row["created_at"]),
    )


def mint(conn, *, kind: str, prompt: str, options: Sequence[str], expects_freetext: bool = False,
         thesis_ref: str | None = None, trigger_ref: int | None = None,
         alert_ref: int | None = None, deadline: str | None = None,
         run_id: int | None = None, clock: Clock) -> Ask:
    """Create the '<K><seq>' row (K in {A,Q,R,F,V,N}) BEFORE any message exists (tg-spec §3.1)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    seq = db.next_ask_seq(conn, kind)
    ask_id = f"{kind}{seq}"
    db.append_ask(conn, {
        "ask_id": ask_id, "kind": kind, "seq": seq, "created_at": db.to_iso(clock.now()),
        "prompt": prompt, "options_json": json.dumps(list(options)),
        "expects_freetext": 1 if expects_freetext else 0,
        "thesis_ref": thesis_ref, "trigger_ref": trigger_ref, "alert_ref": alert_ref,
        "deadline": deadline, "run_id": run_id,
    })
    return _row_to_ask(db.fetch_ask(conn, ask_id))


def get(conn, ask_id: str) -> Ask | None:
    row = db.fetch_ask(conn, ask_id)
    return _row_to_ask(row) if row else None


def open_asks(conn, *, kind: str | None = None) -> list[Ask]:
    """Open + reprompted asks (the /status open-loops list)."""
    return [_row_to_ask(r) for r in db.fetch_open_asks(conn, kind=kind)
            if r["status"] in ("open", "reprompted")]
