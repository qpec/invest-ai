"""Task 7 — yfinance-backed default FX factory (injectable, memoized).

No network: every test injects a fake `rate_lookup`. The real yfinance path is
exercised only in production (never here). `state_dir` is a dummy tmp_path threaded
straight to `rate_lookup`.
"""
from __future__ import annotations

import pytest

from agentcy.fetch.etoro import EtoroError, default_fx


def test_eur_is_identity_and_never_looks_up(tmp_path):
    called = {"n": 0}

    def rate_lookup(pair, *, state_dir):  # pragma: no cover - must never run
        called["n"] += 1
        raise AssertionError("rate_lookup must not be called for EUR")

    fx = default_fx(tmp_path, rate_lookup=rate_lookup)
    assert fx(100.0, "EUR") == 100.0
    assert called["n"] == 0


def test_usd_conversion_uses_documented_convention(tmp_path):
    # EURUSD=X = 1.08 USD per 1 EUR; 108 USD / 1.08 == 100 EUR.
    def rate_lookup(pair, *, state_dir):
        assert pair == "EURUSD=X"
        return 1.08

    fx = default_fx(tmp_path, rate_lookup=rate_lookup)
    assert fx(108.0, "USD") == pytest.approx(100.0)


def test_memoization_one_fetch_per_currency(tmp_path):
    calls = {"n": 0}

    def rate_lookup(pair, *, state_dir):
        calls["n"] += 1
        return 1.08

    fx = default_fx(tmp_path, rate_lookup=rate_lookup)
    fx(100.0, "USD")
    fx(200.0, "USD")
    # EUR in between is identity and must not touch the counter.
    assert fx(50.0, "EUR") == 50.0
    fx(300.0, "USD")
    assert calls["n"] == 1


def test_fail_loud_when_lookup_raises(tmp_path):
    def rate_lookup(pair, *, state_dir):
        raise RuntimeError("yahoo down")

    fx = default_fx(tmp_path, rate_lookup=rate_lookup)
    with pytest.raises(EtoroError, match="FX rate unavailable for USD"):
        fx(100.0, "USD")


@pytest.mark.parametrize("bad", [0.0, -1.0, None])
def test_fail_loud_on_nonpositive_or_none_rate(tmp_path, bad):
    def rate_lookup(pair, *, state_dir):
        return bad

    fx = default_fx(tmp_path, rate_lookup=rate_lookup)
    with pytest.raises(EtoroError, match="FX rate unavailable for USD"):
        fx(100.0, "USD")


def test_case_insensitive_eur_is_identity(tmp_path):
    def rate_lookup(pair, *, state_dir):  # pragma: no cover - must never run
        raise AssertionError("rate_lookup must not be called for eur")

    fx = default_fx(tmp_path, rate_lookup=rate_lookup)
    assert fx(100.0, "eur") == 100.0
