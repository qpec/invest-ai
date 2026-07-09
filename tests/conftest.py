"""Shared fixtures — contract per docs 00-contracts.md §4. Do not weaken the guards."""
from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

# --- (a) autouse no-network socket guard (tech-arch §13) ---------------------

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every test runs offline: any real socket connect raises immediately."""
    def _blocked(*_args, **_kwargs):
        raise RuntimeError(
            "network access attempted during a test (no-network guard, tech-arch §13); "
            "use tests/fixtures/yf/ recordings instead"
        )
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


# --- (b) fresh migrated SQLite in tmp_path ------------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Fresh, fully-migrated agentcy.db under tmp_path; AGENTCY_STATE_DIR points there
    (nothing may hardcode /var/lib at import time)."""
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    from agentcy import db
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    yield conn
    conn.close()


# --- (c) fixed clock ------------------------------------------------------------

@pytest.fixture()
def fixed_clock():
    """Deterministic Clock pinned to 2026-07-08 05:00 UTC (07:00 Europe/Amsterdam);
    injectable everywhere an as_of/clock parameter exists."""
    from agentcy.clock import FixedClock
    return FixedClock(datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc))


# --- golden-file comparison ------------------------------------------------------

GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.fixture()
def golden():
    """Byte-exact golden comparison (the no-LLM decision makes goldens the output-format
    spec). Record/update with UPDATE_GOLDEN=1; a missing golden is a failure otherwise."""
    def _assert(name: str, actual: str) -> None:
        path = GOLDEN_DIR / name
        if os.environ.get("UPDATE_GOLDEN") == "1":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8", newline="")
            return
        assert path.exists(), f"missing golden file {path}; run: UPDATE_GOLDEN=1 uv run pytest -q"
        expected = path.read_text(encoding="utf-8")
        assert actual == expected, f"golden mismatch: {name}"
    return _assert


# --- recorded yfinance fixtures ----------------------------------------------------

YF_FIXTURES = Path(__file__).parent / "fixtures" / "yf"


@pytest.fixture()
def yf_fixture():
    """Load a recorded yfinance response (tools/record_fixtures.py) as parsed JSON."""
    def _load(name: str):
        return json.loads((YF_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return _load

# --- phase-specific fixtures go below this line only ------------------------------
