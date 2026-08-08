"""Shared pytest setup: make the flat stock-scout scripts (universe.py, scoring.py, ...)
importable from the tests directory without any package install (RECONSTRUCTION.md §2),
and hold the same no-network guard the root suite holds."""
import socket
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every test runs offline: any real socket connect raises immediately.

    The root suite has had this guard since the tech architecture (§13); this suite did
    not, which was an asymmetry rather than a decision — the modules under test here
    (enrich.py, prices.py, populate.py, universe.py) are exactly the ones that reach for
    EDGAR and yfinance, so an accidentally-live fetch would have gone unnoticed here and
    made the suite slow, flaky and dependent on someone else's uptime. Tests that need
    fetch behaviour use recordings/fakes, as they already did.
    """
    def _blocked(*_args, **_kwargs):
        raise RuntimeError(
            "network access attempted during a test (no-network guard); "
            "use a recorded fixture or a fake instead"
        )
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
