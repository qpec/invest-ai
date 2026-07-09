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


def test_rate_limit_backoff_ladder_then_rate_limited(tmp_path, no_sleep):
    from agentcy.fetch import yf as yfd
    from yfinance.exceptions import YFRateLimitError
    calls = {"n": 0}

    def always_429():
        calls["n"] += 1
        raise YFRateLimitError()

    with pytest.raises(yfd.RateLimited):
        yfd._paced_call(tmp_path, always_429)
    assert calls["n"] == 4                                   # initial + 3 backoff retries
    assert [s for s in no_sleep if s >= 30] == [30.0, 300.0, 1800.0]  # §7.2 ladder
    # every attempt was paced (4 pacing sleeps interleaved)
    assert len([s for s in no_sleep if s < 30]) == 4


def test_rate_limit_recovers_after_one_429(tmp_path, no_sleep):
    from agentcy.fetch import yf as yfd
    from yfinance.exceptions import YFRateLimitError
    calls = {"n": 0}

    def once_429():
        calls["n"] += 1
        if calls["n"] == 1:
            raise YFRateLimitError()
        return "ok"

    assert yfd._paced_call(tmp_path, once_429) == "ok"
    assert [s for s in no_sleep if s >= 30] == [30.0]        # no retry storm


def test_non_rate_limit_errors_propagate_unretried(tmp_path, no_sleep):
    from agentcy.fetch import yf as yfd
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise ValueError("upstream schema change")

    with pytest.raises(ValueError):
        yfd._paced_call(tmp_path, broken)
    assert calls["n"] == 1                                   # fail loud, no blind retries (§7.1)


def _patch_history(monkeypatch, frame, currency):
    from agentcy.fetch import yf as yfd
    monkeypatch.setattr(yfd, "_raw_history", lambda ticker, period: (frame, currency))


def test_fetch_daily_bars_normalizes_with_dividends(monkeypatch, tmp_path, no_sleep, yf_frame):
    from agentcy.fetch import yf as yfd
    frame, currency = yf_frame("msft_history")
    _patch_history(monkeypatch, frame, currency)
    out = yfd.fetch_daily_bars("MSFT", state_dir=tmp_path)
    assert list(out.columns) == ["close", "adj_close", "dividend", "currency"]
    assert len(out) == 10
    assert out.loc[pd.Timestamp("2026-07-07"), "close"] == pytest.approx(523.60)
    assert out.loc[pd.Timestamp("2026-06-26"), "dividend"] == pytest.approx(0.83)  # BUF-2 feed
    assert out.loc[pd.Timestamp("2026-06-23"), "adj_close"] == pytest.approx(507.27)
    assert (out["currency"] == "USD").all()


def test_fetch_daily_bars_fx_and_benchmark_ride_same_door(monkeypatch, tmp_path, no_sleep, yf_frame):
    from agentcy.fetch import yf as yfd
    fx, fx_cur = yf_frame("eurusd_fx")
    _patch_history(monkeypatch, fx, fx_cur)
    out = yfd.fetch_daily_bars("USDEUR=X", state_dir=tmp_path)
    assert (out["currency"] == "EUR").all() and len(out) == 5


def test_fetch_daily_bars_empty_frame_is_failure(monkeypatch, tmp_path, no_sleep, yf_frame):
    from agentcy.fetch import yf as yfd
    empty, _ = yf_frame("empty_frame_0x0")
    _patch_history(monkeypatch, empty, "USD")
    with pytest.raises(yfd.FetchFailed, match="empty"):
        yfd.fetch_daily_bars("MSFT", state_dir=tmp_path)


def test_fetch_daily_bars_none_frame_is_failure(monkeypatch, tmp_path, no_sleep):
    from agentcy.fetch import yf as yfd
    _patch_history(monkeypatch, None, "USD")
    with pytest.raises(yfd.FetchFailed):
        yfd.fetch_daily_bars("MSFT", state_dir=tmp_path)


def test_fetch_daily_bars_nan_close_is_failure(monkeypatch, tmp_path, no_sleep, yf_frame):
    from agentcy.fetch import yf as yfd
    frame, currency = yf_frame("msft_history")
    frame = frame.copy()
    frame.loc[frame.index[3], "Close"] = float("nan")
    _patch_history(monkeypatch, frame, currency)
    with pytest.raises(yfd.FetchFailed, match="NaN"):
        yfd.fetch_daily_bars("MSFT", state_dir=tmp_path)


def test_fetch_daily_bars_non_positive_close_is_failure(monkeypatch, tmp_path, no_sleep, yf_frame):
    from agentcy.fetch import yf as yfd
    frame, currency = yf_frame("msft_history")
    frame = frame.copy()
    frame.loc[frame.index[0], "Close"] = 0.0
    _patch_history(monkeypatch, frame, currency)
    with pytest.raises(yfd.FetchFailed, match="non-positive"):
        yfd.fetch_daily_bars("MSFT", state_dir=tmp_path)


def test_fetch_daily_bars_missing_currency_is_failure(monkeypatch, tmp_path, no_sleep, yf_frame):
    from agentcy.fetch import yf as yfd
    frame, _ = yf_frame("msft_history")
    _patch_history(monkeypatch, frame, None)
    with pytest.raises(yfd.FetchFailed, match="currency"):
        yfd.fetch_daily_bars("MSFT", state_dir=tmp_path)


def _patch_statements(monkeypatch, stmts, now=FIXED_NOW):
    from agentcy.fetch import yf as yfd
    monkeypatch.setattr(yfd, "_raw_statements", lambda ticker: stmts)
    monkeypatch.setattr(yfd, "_utcnow", lambda: now)


def test_fetch_statements_healthy_passthrough(monkeypatch, tmp_path, no_sleep, yf_statements):
    from agentcy.fetch import yf as yfd
    stmts = yf_statements()
    _patch_statements(monkeypatch, stmts)
    out = yfd.fetch_statements("MSFT", state_dir=tmp_path)
    assert set(out) == {"income", "balance", "cashflow"}
    assert out["cashflow"].loc["Operating Cash Flow"].iloc[0] == pytest.approx(3.6e10)


def test_fetch_statements_0x0_frame_is_failure(monkeypatch, tmp_path, no_sleep, yf_statements, yf_frame):
    # verified failure mode: missing fundamentals arrive as (0,0) frames with NO exception (§7.3)
    from agentcy.fetch import yf as yfd
    stmts = yf_statements()
    empty, _ = yf_frame("empty_frame_0x0")
    stmts["balance"] = empty
    _patch_statements(monkeypatch, stmts)
    with pytest.raises(yfd.FetchFailed, match="balance"):
        yfd.fetch_statements("MSFT", state_dir=tmp_path)


def test_fetch_statements_missing_pinned_row_is_failure(monkeypatch, tmp_path, no_sleep, yf_statements):
    from agentcy.fetch import yf as yfd
    stmts = yf_statements()
    stmts["income"] = stmts["income"].drop(index="EBITDA")
    _patch_statements(monkeypatch, stmts)
    with pytest.raises(yfd.FetchFailed, match="EBITDA"):
        yfd.fetch_statements("MSFT", state_dir=tmp_path)


def test_fetch_statements_implausible_row_count_is_failure(monkeypatch, tmp_path, no_sleep, yf_statements):
    from agentcy.fetch import yf as yfd
    stmts = yf_statements()
    keep = ["Total Revenue", "EBITDA", "Net Income"]           # pinned rows present, but garbled/thin
    stmts["income"] = stmts["income"].loc[keep]
    _patch_statements(monkeypatch, stmts)
    with pytest.raises(yfd.FetchFailed, match="row count"):
        yfd.fetch_statements("MSFT", state_dir=tmp_path)


def test_fetch_statements_stale_period_end_is_failure(monkeypatch, tmp_path, no_sleep, yf_statements):
    from agentcy.fetch import yf as yfd
    stmts = yf_statements()
    _patch_statements(monkeypatch, stmts, now=datetime(2027, 9, 1, tzinfo=timezone.utc))
    with pytest.raises(yfd.FetchFailed, match="not recent"):
        yfd.fetch_statements("MSFT", state_dir=tmp_path)
