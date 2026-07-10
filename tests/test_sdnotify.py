"""P7.1: sd_notify writes to the AF_UNIX datagram socket named by NOTIFY_SOCKET (tech-arch §5.2/§16 stdlib sd_notify)."""
from __future__ import annotations

import socket

import pytest

from agentcy import sdnotify

# AF_UNIX datagram is a Linux/systemd capability; skip the socket-binding cases on
# platforms without it (Windows dev box) — mirrors the git-binary skips in
# test_archive.py / test_gitio.py. The no-op case below has no such dependency.
needs_af_unix = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="AF_UNIX datagram socket required (Linux/systemd target)"
)


def _bind_fake(tmp_path, monkeypatch):
    sock_path = tmp_path / "notify.sock"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(str(sock_path))
    srv.settimeout(1.0)
    monkeypatch.setenv("NOTIFY_SOCKET", str(sock_path))
    return srv


@needs_af_unix
def test_notify_sends_the_literal_state_bytes(tmp_path, monkeypatch):
    srv = _bind_fake(tmp_path, monkeypatch)
    try:
        sdnotify.notify("WATCHDOG=1")
        data, _ = srv.recvfrom(64)
        assert data == b"WATCHDOG=1"
    finally:
        srv.close()


@needs_af_unix
def test_ready_sends_ready_line(tmp_path, monkeypatch):
    srv = _bind_fake(tmp_path, monkeypatch)
    try:
        sdnotify.ready()
        data, _ = srv.recvfrom(64)
        assert data == b"READY=1"
    finally:
        srv.close()


def test_notify_is_a_noop_without_socket_env(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    # Must not raise when run outside systemd (tests, desk).
    sdnotify.notify("WATCHDOG=1")


@needs_af_unix
def test_abstract_namespace_socket_supported(tmp_path, monkeypatch):
    # systemd may hand an abstract socket whose name starts with '@'.
    name = "\0agentcy-test-notify"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(name)
    srv.settimeout(1.0)
    monkeypatch.setenv("NOTIFY_SOCKET", "@agentcy-test-notify")
    try:
        sdnotify.notify("WATCHDOG=1")
        data, _ = srv.recvfrom(64)
        assert data == b"WATCHDOG=1"
    finally:
        srv.close()
