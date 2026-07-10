"""Dead-man ping — the system's SOLE third-party touchpoint (S2, owner-ratified ON).

Single source (R4): the daily job fires ping(conn) exactly once after a successful
sweep. A content-free HTTPS GET tells an external monitor "the box is alive"; an empty
URL (pre-install) is a no-op, and any failure is swallowed — the ping must never fail
the run it reports on. URL resolves from env AGENTCY_DEADMAN_URL, else config
'deadman_ping_url' (P8 wires the env/config; it never re-creates this module).
"""
from __future__ import annotations

import os
import urllib.request

from agentcy import config


def resolve_url(conn) -> str:
    """env AGENTCY_DEADMAN_URL takes precedence over the journaled config value."""
    return os.environ.get("AGENTCY_DEADMAN_URL") or config.get(conn, "deadman_ping_url")


def ping(conn) -> None:
    """Content-free HTTPS GET; empty URL = no-op; never raises, never fails the run."""
    url = resolve_url(conn)
    if not url:
        return
    try:
        urllib.request.urlopen(url, timeout=10).close()
    except Exception:
        pass
