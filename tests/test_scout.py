"""tests/test_scout.py — The Scout (H.1/H.2), P4."""
from __future__ import annotations

import bz2
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from agentcy import scout


TINY_CSV = (
    "symbol,name,sector,industry,country,market_cap\n"
    "VEEV,Veeva,Technology,Software,United States,large_cap\n"
    "ASML,ASML,Technology,Semiconductors,Netherlands,large_cap\n"
)


@pytest.fixture()
def universe_file(tmp_path):
    """A tiny bz2 the tests generate + hash inline (the real 160k-row file is a
    pinned-commit desk asset; the read logic is identical)."""
    raw = TINY_CSV.encode("utf-8")
    path = tmp_path / "equities.bz2"
    path.write_bytes(bz2.compress(raw))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, sha


def test_load_universe_reads_rows(universe_file):
    path, sha = universe_file
    df = scout.load_universe(path, expect_sha=sha)
    assert list(df["symbol"]) == ["VEEV", "ASML"]


def test_load_universe_rejects_wrong_sha(universe_file):
    path, _ = universe_file
    with pytest.raises(scout.UniverseSHAError):
        scout.load_universe(path, expect_sha="0" * 64)


def test_load_universe_empty_sha_pin_refuses(universe_file):
    path, sha = universe_file
    # an unset pin ('' in config) must not silently pass any file
    with pytest.raises(scout.UniverseSHAError):
        scout.load_universe(path, expect_sha="")
