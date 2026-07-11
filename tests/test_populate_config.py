"""The four journaled populator config defaults (populator design 7)."""
from agentcy import config


def test_populate_defaults_are_seeded(tmp_db):
    assert config.get(tmp_db, "populate_enabled") == "true"
    assert config.get_int(tmp_db, "populate_starter_size") == 500
    assert config.get_int(tmp_db, "populate_nightly_minutes") == 90
    assert config.get_int(tmp_db, "populate_dead_after_failures") == 3


def test_populate_keys_are_journaled_and_overridable(tmp_db):
    from agentcy.clock import FixedClock
    from datetime import datetime, timezone
    clk = FixedClock(datetime(2026, 7, 10, tzinfo=timezone.utc))
    config.set(tmp_db, "populate_starter_size", "250", reason="tune", actor="owner", clock=clk)
    assert config.get_int(tmp_db, "populate_starter_size") == 250
