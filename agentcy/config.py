"""Config reads + journaled changes: an unjournaled change is a FK violation (tech-arch §9)."""
from __future__ import annotations

from agentcy import db
from agentcy.clock import Clock


def get(conn, key: str, *, as_of: str | None = None) -> str:
    """Latest config value (E.3 defaults seeded by migration 000)."""
    current = db.fetch_config_current(conn, as_of=as_of)
    if key not in current:
        raise KeyError(f"unknown config key at {as_of or 'now'}: {key!r}")
    return current[key]


def get_float(conn, key: str) -> float:
    return float(get(conn, key))


def get_int(conn, key: str) -> int:
    return int(get(conn, key))


def set(conn, key: str, value: str, *, reason: str, actor: str, clock: Clock) -> int:
    """Journal-entry-first, then config append, ONE transaction (§9); returns journal entry_id."""
    ts = db.to_iso(clock.now())
    with conn:                       # commit on success, rollback both writes on failure
        entry_id = db.append_journal_entry(conn, {
            "ts": ts,
            "decision_type": "config_or_designation",
            "decision_subtype": "config_change",
            "reasoning_at_the_moment": reason,
            "actor": actor,
        })
        db.append_config(conn, key=key, value=value, valid_from=ts,
                         journal_ref=entry_id)
    return entry_id


def effective(conn, *, as_of: str | None = None) -> dict[str, str]:
    """Full effective config — embedded into run_log.inputs_json by runlog.start."""
    return db.fetch_config_current(conn, as_of=as_of)
