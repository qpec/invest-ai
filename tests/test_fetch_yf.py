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


def test_yahoo_pacing_lock_file_and_spacing_inside_lock(tmp_path, no_sleep):
    from agentcy.fetch import yf as yfd
    with yfd.yahoo_pacing(tmp_path):
        assert (tmp_path / "locks" / "yahoo.lock").exists()
        assert no_sleep == []            # spacing happens AFTER the call, before release
    assert len(no_sleep) == 1
    assert 2.5 <= no_sleep[0] <= 3.5     # >=2s base + 0.5-1.5s jitter (§7.2)


def test_yahoo_pacing_spaces_even_when_body_raises(tmp_path, no_sleep):
    from agentcy.fetch import yf as yfd
    with pytest.raises(RuntimeError):
        with yfd.yahoo_pacing(tmp_path):
            raise RuntimeError("boom")
    assert len(no_sleep) == 1            # a failed call still hit Yahoo — space it


def test_yahoo_pacing_reentrant_sequential(tmp_path, no_sleep):
    from agentcy.fetch import yf as yfd
    with yfd.yahoo_pacing(tmp_path):
        pass
    with yfd.yahoo_pacing(tmp_path):
        pass
    assert len(no_sleep) == 2            # lock released each time; stale lock file harmless (fd-scoped)
