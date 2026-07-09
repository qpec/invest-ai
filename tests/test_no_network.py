"""Proves the autouse no-network guard (tech-arch §13): any real socket
connect inside a test raises RuntimeError, structurally."""
from __future__ import annotations

import socket

import pytest


def test_create_connection_blocked():
    with pytest.raises(RuntimeError, match="no-network guard"):
        socket.create_connection(("127.0.0.1", 9))


def test_socket_connect_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="no-network guard"):
            s.connect(("127.0.0.1", 9))
    finally:
        s.close()
