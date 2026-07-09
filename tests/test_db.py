"""db.py basics: state_dir resolution, ISO-8601 round-trip."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from agentcy import db


def test_state_dir_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    assert db.state_dir() == tmp_path


def test_state_dir_default(monkeypatch):
    monkeypatch.delenv("AGENTCY_STATE_DIR", raising=False)
    assert db.state_dir() == Path("/var/lib/stock-agentcy")


def test_to_iso_normalizes_to_utc_z():
    cet = timezone(timedelta(hours=2))
    assert db.to_iso(datetime(2026, 7, 8, 7, 0, tzinfo=cet)) == "2026-07-08T05:00:00Z"


def test_to_iso_rejects_naive():
    with pytest.raises(ValueError):
        db.to_iso(datetime(2026, 7, 8, 7, 0))


def test_from_iso_round_trip():
    dt = db.from_iso("2026-07-08T05:00:00Z")
    assert dt == datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)
    assert db.to_iso(dt) == "2026-07-08T05:00:00Z"
