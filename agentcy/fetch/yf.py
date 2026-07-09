# agentcy/fetch/yf.py
"""THE ONLY yfinance importer (tech-arch §7; contracts §3.6).

Fail-loud config, box-wide flock pacing (spacing inside the lock), rate-limit
backoff, empty-is-failure validation. Never the `info` accessor — fast_info +
statements only, with the one named officers quoteSummary exception (§7.2).
"""
from __future__ import annotations

import random
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError


class FetchFailed(Exception):
    """Empty/None/zero-row frame, NaN/non-positive closes, or transport failure — empty is failure (§7.3)."""


class RateLimited(FetchFailed):
    """YFRateLimitError surfaced after the full backoff ladder; the caller marks the run DEGRADED (§7.2)."""


_configured = False


def configure() -> None:
    """Fail-loud yfinance config: hide_exceptions=False, network.retries=2 — called once before any fetch (§7.1)."""
    global _configured
    if _configured:
        return
    yf.config.debug.hide_exceptions = False
    yf.config.network.retries = 2
    _configured = True


def _utcnow() -> datetime:
    """Seam for the statement-sanity recency check (tests pin it; runtime = wall clock)."""
    return datetime.now(timezone.utc)
