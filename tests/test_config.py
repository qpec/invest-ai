"""Journal-entry-first config writes, one transaction (contracts §3.4, tech-arch §9)."""
from __future__ import annotations

import sqlite3

import pytest

from agentcy import config

AFTER_SEEDS = "2026-07-10T00:00:00Z"   # past both seed valid_from days (07-08 and 07-09)


def test_get_seeded_defaults(tmp_db):
    assert config.get(tmp_db, "cash_band_low_pct", as_of=AFTER_SEEDS) == "5"
    assert config.get(tmp_db, "license_exceptions", as_of=AFTER_SEEDS) == "certifi:MPL-2.0"
    assert config.get_float(tmp_db, "min_effective_bets") == 4.0
    assert config.get_int(tmp_db, "alert_decision_days") == 7


def test_get_unknown_key_raises(tmp_db):
    with pytest.raises(KeyError):
        config.get(tmp_db, "no_such_key", as_of=AFTER_SEEDS)


def test_set_is_journal_first_in_one_transaction(tmp_db, fixed_clock):
    eid = config.set(tmp_db, "alert_decision_days", "10",
                     reason="calmer cadence", actor="owner", clock=fixed_clock)
    row = tmp_db.execute(
        "SELECT * FROM config WHERE key='alert_decision_days'"
        " ORDER BY valid_from DESC LIMIT 1").fetchone()
    assert row["value"] == "10" and row["journal_ref"] == eid
    assert row["valid_from"] == "2026-07-08T05:00:00Z"
    je = tmp_db.execute("SELECT * FROM journal_entry WHERE entry_id=?", (eid,)).fetchone()
    assert je["decision_type"] == "config_or_designation"
    assert je["decision_subtype"] == "config_change"
    assert je["reasoning_at_the_moment"] == "calmer cadence"
    assert je["actor"] == "owner"
    assert config.get(tmp_db, "alert_decision_days", as_of=AFTER_SEEDS) == "10"


def test_set_rolls_back_journal_entry_on_config_failure(tmp_db, fixed_clock):
    config.set(tmp_db, "screen_recipe", "qv2", reason="r", actor="owner",
               clock=fixed_clock)
    n_before = tmp_db.execute("SELECT COUNT(*) FROM journal_entry").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):        # same (key, valid_from) PK
        config.set(tmp_db, "screen_recipe", "qv3", reason="dup", actor="owner",
                   clock=fixed_clock)
    n_after = tmp_db.execute("SELECT COUNT(*) FROM journal_entry").fetchone()[0]
    assert n_after == n_before                          # ONE transaction: both or neither


def test_effective_returns_full_current_map(tmp_db):
    eff = config.effective(tmp_db, as_of=AFTER_SEEDS)
    assert len(eff) == 25 and eff["benchmark"] == "SP500TR_EUR"
