"""P6.16: quantstats quarantined behind try/except; the four-stat hand fallback always answers."""
import sys
import types

import pandas as pd

from agentcy.jobs import quarterly


def _series():
    idx = pd.date_range("2026-07-01", periods=5, freq="D")
    return pd.Series([100.0, 102.0, 99.0, 101.0, 104.0], index=idx)


def test_hand_fallback_four_stats_present():
    port = _series().pct_change().dropna()
    bench = (_series() * 0.99).pct_change().dropna()
    stats = quarterly.hand_stats(port, bench)
    assert set(stats) >= {"period_return", "vs_benchmark_simple", "max_drawdown", "volatility"}
    assert stats["max_drawdown"] <= 0.0


def test_compute_stats_falls_back_when_quantstats_raises(monkeypatch):
    # inject a quantstats stub whose reports.metrics raises -> fallback path taken:
    qs = types.ModuleType("quantstats")
    qs.reports = types.SimpleNamespace(metrics=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setitem(sys.modules, "quantstats", qs)
    port = _series().pct_change().dropna()
    bench = (_series() * 0.99).pct_change().dropna()
    out = quarterly.compute_stats(port, bench)
    assert out["degraded"] is True                          # fell back, still answered
    assert "period_return" in out["stats"]


def test_compute_stats_uses_quantstats_when_available(monkeypatch):
    qs = types.ModuleType("quantstats")
    qs.reports = types.SimpleNamespace(metrics=lambda *a, **k: {"Sharpe": 1.2})
    monkeypatch.setitem(sys.modules, "quantstats", qs)
    port = _series().pct_change().dropna()
    bench = port.copy()
    out = quarterly.compute_stats(port, bench)
    assert out["degraded"] is False
