# tests/test_fetch_yf.py
"""fetch/yf.py — the only yfinance door (tech-arch §7; contracts §3.6)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

FIXED_NOW = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def test_exception_hierarchy():
    from agentcy.fetch import yf as yfd
    assert issubclass(yfd.RateLimited, yfd.FetchFailed)
    assert issubclass(yfd.FetchFailed, Exception)


def test_configure_sets_fail_loud_flags():
    # Exercises the REAL yfinance 1.5.1 config object (no network involved) —
    # this test is the desk canary for the pinned config surface (plan note 7).
    from agentcy.fetch import yf as yfd
    yfd.configure()
    assert yfd.yf.config.debug.hide_exceptions is False   # default hides -> silent None (§7.1)
    assert yfd.yf.config.network.retries == 2
    yfd.configure()  # idempotent — safe to call before every fetch
