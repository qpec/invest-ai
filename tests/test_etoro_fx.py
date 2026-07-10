"""Task 7 — default FX factory built on the canonical store.fx_rate_eur.

No network: every test injects a fake `rate_source` matching the
`store.fx_rate_eur(conn, currency, *, as_of) -> Stamped|None` signature.
The real DB-cache-backed path (store.fx_rate_eur) is exercised elsewhere.
`conn`/`as_of` are dummies threaded straight through to the fake.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from agentcy.fetch.etoro import EtoroError, default_fx
from agentcy.freshness import DataState, Stamped

_AS_OF = datetime(2026, 7, 10)


def _stamped(rate):
    return Stamped(rate, _AS_OF, DataState.FRESH)


def test_eur_is_identity_and_short_circuits():
    # We short-circuit EUR: the canonical helper is never consulted for it.
    called = {"n": 0}

    def rate_source(conn, currency, *, as_of):  # pragma: no cover - must never run for EUR
        called["n"] += 1
        raise AssertionError("rate_source must not be called for EUR")

    fx = default_fx(object(), as_of=_AS_OF, rate_source=rate_source)
    assert fx(100.0, "EUR") == 100.0
    assert called["n"] == 0


def test_usd_conversion_uses_amount_times_rate():
    # USDEUR=X = 0.92 EUR per 1 USD; 100 USD * 0.92 == 92 EUR.
    def rate_source(conn, currency, *, as_of):
        assert currency == "USD"
        assert as_of == _AS_OF
        return _stamped(0.92)

    fx = default_fx(object(), as_of=_AS_OF, rate_source=rate_source)
    assert fx(100.0, "USD") == pytest.approx(92.0)


def test_memoization_one_lookup_per_currency():
    calls = {"n": 0}

    def rate_source(conn, currency, *, as_of):
        calls["n"] += 1
        return _stamped(0.92)

    fx = default_fx(object(), as_of=_AS_OF, rate_source=rate_source)
    assert fx(100.0, "USD") == pytest.approx(92.0)
    assert fx(200.0, "USD") == pytest.approx(184.0)
    assert fx(300.0, "USD") == pytest.approx(276.0)
    assert calls["n"] == 1


def test_fail_loud_when_rate_source_returns_none():
    def rate_source(conn, currency, *, as_of):
        return None

    fx = default_fx(object(), as_of=_AS_OF, rate_source=rate_source)
    with pytest.raises(EtoroError, match="FX rate unavailable for USD"):
        fx(100.0, "USD")


@pytest.mark.parametrize("bad", [0.0, -1.0, None])
def test_fail_loud_on_nonpositive_or_none_rate(bad):
    def rate_source(conn, currency, *, as_of):
        return _stamped(bad)

    fx = default_fx(object(), as_of=_AS_OF, rate_source=rate_source)
    with pytest.raises(EtoroError, match="FX rate unavailable for USD"):
        fx(100.0, "USD")


def test_case_insensitive_currency():
    def rate_source(conn, currency, *, as_of):
        assert currency == "USD"  # upper-cased before lookup
        return _stamped(0.92)

    fx = default_fx(object(), as_of=_AS_OF, rate_source=rate_source)
    assert fx(100.0, "usd") == pytest.approx(92.0)


def test_case_insensitive_eur_is_identity():
    def rate_source(conn, currency, *, as_of):  # pragma: no cover - must never run for eur
        raise AssertionError("rate_source must not be called for eur")

    fx = default_fx(object(), as_of=_AS_OF, rate_source=rate_source)
    assert fx(100.0, "eur") == 100.0
