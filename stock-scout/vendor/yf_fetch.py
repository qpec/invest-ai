# vendor/yf_fetch.py — adapted from agentcy/fetch/yf.py (see vendor/README.md)
"""The hardened yfinance layer, vendored for the stock-scout pipeline.

Fail-loud config, box-wide flock pacing (spacing inside the lock), rate-limit
backoff, empty-is-failure validation. Never the `info` accessor — fast_info +
statements only. Adaptation vs the agentcy original: the pacing interval is
configurable via ``set_pace`` (the scout populate paces ~0.6 s/call; the
runtime's 2 s default is still available), and ``fetch_statements`` can return
annual and/or quarterly frames for the scout cache.
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
    """Empty/None/zero-row frame, NaN/non-positive closes, or transport failure — empty is failure."""


class RateLimited(FetchFailed):
    """YFRateLimitError surfaced after the full backoff ladder; the caller stops/degrades."""


_configured = False


def configure() -> None:
    """Fail-loud yfinance config: hide_exceptions=False, network.retries=2 — called once before any fetch."""
    global _configured
    if _configured:
        return
    yf.config.debug.hide_exceptions = False
    yf.config.network.retries = 2
    _configured = True


def _utcnow() -> datetime:
    """Seam for the statement-sanity recency check (tests pin it; runtime = wall clock)."""
    return datetime.now(timezone.utc)


# Scout default pacing (RECONSTRUCTION.md §6.5): ~0.6 s + jitter per Yahoo call.
# The agentcy runtime value (2.0 s, jitter 0.5–1.5 s) remains reachable via set_pace.
PACE_BASE_SECONDS = 0.6
PACE_JITTER = (0.1, 0.5)


def set_pace(base_seconds: float, jitter: tuple[float, float] | None = None) -> None:
    """Override the per-call spacing (populate --pace)."""
    global PACE_BASE_SECONDS, PACE_JITTER
    PACE_BASE_SECONDS = float(base_seconds)
    if jitter is not None:
        PACE_JITTER = (float(jitter[0]), float(jitter[1]))


try:  # POSIX flock — the deployment target
    import fcntl

    def _lock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_UN)

except ImportError:  # Windows dev box only — parity, never deployed
    import msvcrt

    def _lock(f) -> None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock(f) -> None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def yahoo_pacing(state_dir: Path):
    """Acquire flock on <state_dir>/locks/yahoo.lock and hold the spacing INSIDE the
    lock — one mechanism, box-wide serialization of every Yahoo call."""
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


RATE_LIMIT_BACKOFF: tuple[float, ...] = (30.0, 300.0, 1800.0)  # 30s -> 5min -> 30min


def _paced_call(state_dir: Path, fn):
    """Run one raw Yahoo call inside the pacing lock; on YFRateLimitError back off
    30s -> 5min -> 30min, then raise RateLimited. Backoff sleeps happen OUTSIDE the
    lock so a rate-limit wait never wedges the box-wide pacing for other processes."""
    attempts = len(RATE_LIMIT_BACKOFF) + 1
    for attempt in range(attempts):
        try:
            with yahoo_pacing(state_dir):
                return fn()
        except YFRateLimitError as e:
            if attempt == attempts - 1:
                raise RateLimited(f"rate-limited after {attempts} paced attempts: {e}") from e
            time.sleep(RATE_LIMIT_BACKOFF[attempt])
    raise AssertionError("unreachable")


def _raw_history(yf_ticker: str, period: str):
    """The one Ticker.history touch. auto_adjust=False so Close AND Adj Close arrive;
    actions=True so Dividends AND Stock Splits ride the same bar fetch. Currency comes
    from history_metadata — no extra request."""
    t = yf.Ticker(yf_ticker)
    frame = t.history(period=period, auto_adjust=False, actions=True)
    meta = getattr(t, "history_metadata", None) or {}
    return frame, meta.get("currency")


def fetch_daily_bars(yf_ticker: str, *, state_dir: Path, period: str = "10d") -> pd.DataFrame:
    """Ticker.history bars incl. dividends AND split events; raises FetchFailed on
    empty/NaN/non-positive closes. Returns the normalized frame: DatetimeIndex, columns
    exactly [close, adj_close, dividend, split, currency].

    `split` carries Yahoo's "Stock Splits" ratio (0.0 on ordinary days, e.g. 2.0 on the
    effective date of a 2-for-1). It rides this one history call — populate asks for a
    multi-year `period` so the split history covering the cached share series arrives
    WITHOUT a second Yahoo request (§3.2 "splits", §5.2)."""
    configure()
    frame, currency = _paced_call(state_dir, lambda: _raw_history(yf_ticker, period))
    if frame is None or len(frame) == 0:
        raise FetchFailed(f"{yf_ticker}: empty price frame — empty is failure")
    missing = [c for c in ("Close", "Adj Close") if c not in frame.columns]
    if missing:
        raise FetchFailed(f"{yf_ticker}: history frame missing columns {missing}")
    dividends = frame["Dividends"] if "Dividends" in frame.columns else pd.Series(0.0, index=frame.index)
    splits = frame["Stock Splits"] if "Stock Splits" in frame.columns else pd.Series(0.0, index=frame.index)
    out = pd.DataFrame(
        {
            "close": frame["Close"].astype(float),
            "adj_close": frame["Adj Close"].astype(float),
            "dividend": dividends.fillna(0.0).astype(float),
            "split": splits.fillna(0.0).astype(float),
        },
        index=frame.index,
    )
    if out["close"].isna().any() or out["adj_close"].isna().any():
        raise FetchFailed(f"{yf_ticker}: NaN closes — never write zeros")
    if (out["close"] <= 0).any() or (out["adj_close"] <= 0).any():
        raise FetchFailed(f"{yf_ticker}: non-positive closes")
    if not currency:
        raise FetchFailed(f"{yf_ticker}: no currency in history metadata")
    out["currency"] = str(currency)
    return out


def fetch_weekly_bars(yf_ticker: str, *, state_dir: Path, period: str = "6y") -> pd.DataFrame:
    """Weekly bars for the backtest price grid (bt_fetch.py). Same validation contract
    as fetch_daily_bars; interval=1wk keeps the payload small over multi-year spans."""
    configure()

    def _raw():
        t = yf.Ticker(yf_ticker)
        frame = t.history(period=period, interval="1wk", auto_adjust=False, actions=True)
        meta = getattr(t, "history_metadata", None) or {}
        return frame, meta.get("currency")

    frame, currency = _paced_call(state_dir, _raw)
    if frame is None or len(frame) == 0:
        raise FetchFailed(f"{yf_ticker}: empty weekly price frame — empty is failure")
    if "Adj Close" not in frame.columns:
        raise FetchFailed(f"{yf_ticker}: weekly frame missing Adj Close")
    out = pd.DataFrame({"adj_close": frame["Adj Close"].astype(float)}, index=frame.index)
    out = out[out["adj_close"].notna() & (out["adj_close"] > 0)]
    if len(out) == 0:
        raise FetchFailed(f"{yf_ticker}: no usable weekly closes")
    out["currency"] = str(currency) if currency else ""
    return out


MIN_STATEMENT_ROWS = 8        # plausible-row-count gate (real statements carry dozens)
RECENT_PERIOD_DAYS = 400      # newest annual period_end must be younger than this
PINNED_ROWS = {               # the rows the scoring layer cannot live without
    "income": ("Total Revenue", "EBITDA"),
    "balance": ("Total Debt", "Cash And Cash Equivalents"),
    "cashflow": ("Operating Cash Flow", "Capital Expenditure"),
}


def _raw_statements(yf_ticker: str, freq: str) -> dict:
    t = yf.Ticker(yf_ticker)
    if freq == "quarterly":
        return {
            "income": t.quarterly_income_stmt,
            "balance": t.quarterly_balance_sheet,
            "cashflow": t.quarterly_cashflow,
        }
    return {
        "income": t.income_stmt,
        "balance": t.balance_sheet,
        "cashflow": t.cashflow,
    }


def fetch_statements(yf_ticker: str, *, state_dir: Path, freq: str = "annual",
                     recent_days: int | None = None) -> dict:
    """Income/balance/cashflow at ``freq`` ('annual' | 'quarterly'); statement sanity
    (plausible rows, recent period_end, pinned rows) before return — a failed sanity
    check raises FetchFailed and the caller logs the symbol as a failure."""
    configure()
    frames = _paced_call(state_dir, lambda: _raw_statements(yf_ticker, freq))
    max_age = recent_days if recent_days is not None else (
        RECENT_PERIOD_DAYS if freq == "annual" else 250)
    for stype in ("income", "balance", "cashflow"):
        frame = frames.get(stype)
        if frame is None or frame.shape[0] == 0 or frame.shape[1] == 0:
            raise FetchFailed(
                f"{yf_ticker} {stype} ({freq}): empty statements frame — the verified (0,0) silent-failure shape"
            )
        if frame.shape[0] < MIN_STATEMENT_ROWS:
            raise FetchFailed(
                f"{yf_ticker} {stype} ({freq}): implausible row count {frame.shape[0]} (<{MIN_STATEMENT_ROWS})")
        absent = [r for r in PINNED_ROWS[stype] if r not in frame.index]
        if absent:
            raise FetchFailed(f"{yf_ticker} {stype} ({freq}): pinned rows absent: {absent}")
        newest = max(pd.Timestamp(c) for c in frame.columns)
        if (_utcnow().date() - newest.date()).days > max_age:
            raise FetchFailed(
                f"{yf_ticker} {stype} ({freq}): newest period_end {newest.date()} not recent (>{max_age}d)")
    return frames


def _raw_shares_full(yf_ticker: str):
    return yf.Ticker(yf_ticker).get_shares_full()


def fetch_shares_full(yf_ticker: str, *, state_dir: Path) -> pd.Series:
    """get_shares_full raw series — duplicates included; the cache dedups last-per-date."""
    configure()
    series = _paced_call(state_dir, lambda: _raw_shares_full(yf_ticker))
    if series is None or len(series) == 0:
        raise FetchFailed(f"{yf_ticker}: empty shares series")
    return series


def _raw_fast_info(yf_ticker: str) -> dict:
    return dict(yf.Ticker(yf_ticker).fast_info)


def fetch_fast_info(yf_ticker: str, *, state_dir: Path) -> dict:
    """fast_info only — the bare `info` accessor is banned."""
    configure()
    info = _paced_call(state_dir, lambda: _raw_fast_info(yf_ticker))
    if not info:
        raise FetchFailed(f"{yf_ticker}: empty fast_info")
    return info
