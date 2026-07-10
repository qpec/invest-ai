"""Minimal stdlib systemd sd_notify (tech-arch §5.2, §16 ruling: stdlib sd_notify).

No third party. A no-op when NOTIFY_SOCKET is unset (desk / tests). Handles the
abstract-namespace form ('@name' -> leading NUL) that systemd may hand us.
"""
from __future__ import annotations

import os
import socket


def notify(state: str) -> None:
    """Send one state line to NOTIFY_SOCKET; silent no-op when unset or on send error."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.sendto(state.encode("utf-8"), addr)
        finally:
            sock.close()
    except OSError:
        # Notifying the supervisor must never crash the daemon.
        return


def ready() -> None:
    """READY=1 — emitted once after setMyCommands at daemon start."""
    notify("READY=1")


def watchdog() -> None:
    """WATCHDOG=1 — the loop-top / between-sends / between-handles ping (§5.2)."""
    notify("WATCHDOG=1")
