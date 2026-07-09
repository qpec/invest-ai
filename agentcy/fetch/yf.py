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


PACE_BASE_SECONDS = 2.0
PACE_JITTER = (0.5, 1.5)

try:  # POSIX flock — production (Ubuntu, tech-arch §1.1)
    import fcntl

    def _lock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_UN)

except ImportError:  # Windows dev box only — suite parity, never deployed (plan note 3)
    import msvcrt

    def _lock(f) -> None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock(f) -> None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def yahoo_pacing(state_dir: Path):
    """Acquire flock on <state_dir>/locks/yahoo.lock and hold the >=2s + 0.5-1.5s jitter
    spacing INSIDE the lock (§7.2) — one mechanism, box-wide serialization of every
    Yahoo call (daily job, Saturday batch, event checks, desk Gate runs)."""
    lock_dir = Path(state_dir) / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with open(lock_dir / "yahoo.lock", "a+b") as f:
        _lock(f)
        try:
            yield
        finally:
            # Spacing inside the lock: the next acquirer anywhere on the box waits it out.
            time.sleep(PACE_BASE_SECONDS + random.uniform(*PACE_JITTER))
            _unlock(f)


RATE_LIMIT_BACKOFF: tuple[float, ...] = (30.0, 300.0, 1800.0)  # 30s -> 5min -> 30min (§7.2)


def _paced_call(state_dir: Path, fn):
    """Run one raw Yahoo call inside the pacing lock; on YFRateLimitError back off
    30s -> 5min -> 30min, then raise RateLimited — the caller marks the run DEGRADED
    and stops; no retry storms (§7.2). Backoff sleeps happen OUTSIDE the lock so a
    rate-limit wait never wedges the box-wide pacing for other processes."""
    attempts = len(RATE_LIMIT_BACKOFF) + 1
    for attempt in range(attempts):
        try:
            with yahoo_pacing(state_dir):
                return fn()
        except YFRateLimitError as e:
            if attempt == attempts - 1:
                raise RateLimited(f"rate-limited after {attempts} paced attempts (§7.2): {e}") from e
            time.sleep(RATE_LIMIT_BACKOFF[attempt])
    raise AssertionError("unreachable")


def _raw_history(yf_ticker: str, period: str):
    """The one Ticker.history touch. auto_adjust=False so Close AND Adj Close arrive;
    actions=True so Dividends ride the same bar fetch (BUF-2). Currency comes from
    history_metadata — no extra request."""
    t = yf.Ticker(yf_ticker)
    frame = t.history(period=period, auto_adjust=False, actions=True)
    meta = getattr(t, "history_metadata", None) or {}
    return frame, meta.get("currency")


def fetch_daily_bars(yf_ticker: str, *, state_dir: Path, period: str = "10d") -> pd.DataFrame:
    """Ticker.history bars incl. dividends; raises FetchFailed on empty/NaN/non-positive
    closes (§7.3). FX pairs and ^SP500TR ride this same door. Returns the normalized
    frame: DatetimeIndex, columns exactly [close, adj_close, dividend, currency]."""
    configure()
    frame, currency = _paced_call(state_dir, lambda: _raw_history(yf_ticker, period))
    if frame is None or len(frame) == 0:
        raise FetchFailed(f"{yf_ticker}: empty price frame — empty is failure (§7.3)")
    missing = [c for c in ("Close", "Adj Close") if c not in frame.columns]
    if missing:
        raise FetchFailed(f"{yf_ticker}: history frame missing columns {missing}")
    dividends = frame["Dividends"] if "Dividends" in frame.columns else pd.Series(0.0, index=frame.index)
    out = pd.DataFrame(
        {
            "close": frame["Close"].astype(float),
            "adj_close": frame["Adj Close"].astype(float),
            "dividend": dividends.fillna(0.0).astype(float),
        },
        index=frame.index,
    )
    if out["close"].isna().any() or out["adj_close"].isna().any():
        raise FetchFailed(f"{yf_ticker}: NaN closes — never write zeros (§7.3)")
    if (out["close"] <= 0).any() or (out["adj_close"] <= 0).any():
        raise FetchFailed(f"{yf_ticker}: non-positive closes (§7.3)")
    if not currency:
        raise FetchFailed(f"{yf_ticker}: no currency in history metadata")
    out["currency"] = str(currency)
    return out
