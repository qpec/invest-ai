"""Task 8 Piece A — production_fx (self-priming FX).

default_fx (Task 7) fails loud on a cache miss. production_fx wraps it with a
rate_source that fetches {CUR}EUR=X on a miss and stores it, so a first eToro pull
(nothing cached yet) self-heals. All network/DB-price seams are injected, so these
tests never touch yfinance or the DB.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agentcy.fetch import etoro
from agentcy.fetch.etoro import EtoroError, production_fx
from agentcy.fetch.yf import FetchFailed
from agentcy.freshness import DataState, Stamped


class _Clock:
    def now(self):
        return datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)


_AS_OF = datetime(2026, 7, 10)


def _stamped(rate):
    return Stamped(rate, _AS_OF, DataState.FRESH)


def test_cache_miss_primes_then_returns_amount_times_rate(monkeypatch):
    # First fx_rate_eur read misses (None); after a fake bar_store primes the cache,
    # the re-read returns a Stamped. Assert exactly one fetch+store for the pair.
    reads = {"n": 0}

    def fake_fx_rate_eur(conn, cur, *, as_of):
        reads["n"] += 1
        # miss on the first read, hit after priming
        return None if reads["n"] == 1 else _stamped(0.92)

    monkeypatch.setattr(etoro.store, "fx_rate_eur", fake_fx_rate_eur)

    fetched = []
    stored = []

    def fake_bar_fetcher(pair, *, state_dir):
        fetched.append((pair, state_dir))
        return "FRAME"

    def fake_bar_store(conn, pair, frame, *, run_id, fetched_at):
        stored.append((pair, frame, run_id, fetched_at))
        return 1

    fx = production_fx(
        object(), as_of=_AS_OF, state_dir="STATE", clock=_Clock(),
        bar_fetcher=fake_bar_fetcher, bar_store=fake_bar_store)

    assert fx(100.0, "USD") == pytest.approx(92.0)
    assert fetched == [("USDEUR=X", "STATE")]
    assert len(stored) == 1
    pair, frame, run_id, fetched_at = stored[0]
    assert pair == "USDEUR=X"
    assert frame == "FRAME"
    assert run_id is None
    assert fetched_at == "2026-07-10T06:00:00Z"  # db.to_iso(clock.now())


def test_warm_cache_does_not_fetch(monkeypatch):
    monkeypatch.setattr(etoro.store, "fx_rate_eur",
                        lambda conn, cur, *, as_of: _stamped(0.92))
    calls = {"fetch": 0}

    def fake_bar_fetcher(pair, *, state_dir):  # pragma: no cover - must not run
        calls["fetch"] += 1
        raise AssertionError("warm cache must not fetch")

    fx = production_fx(
        object(), as_of=_AS_OF, state_dir="STATE", clock=_Clock(),
        bar_fetcher=fake_bar_fetcher, bar_store=lambda *a, **k: 0)

    assert fx(100.0, "USD") == pytest.approx(92.0)
    assert calls["fetch"] == 0


def test_fetch_failed_raises_etoro_error(monkeypatch):
    monkeypatch.setattr(etoro.store, "fx_rate_eur",
                        lambda conn, cur, *, as_of: None)

    def boom(pair, *, state_dir):
        raise FetchFailed("network down")

    fx = production_fx(
        object(), as_of=_AS_OF, state_dir="STATE", clock=_Clock(),
        bar_fetcher=boom, bar_store=lambda *a, **k: 0)

    with pytest.raises(EtoroError, match="FX fetch failed for USDEUR=X"):
        fx(100.0, "USD")


def test_still_unavailable_after_prime_raises_etoro_error(monkeypatch):
    # Fetch+store succeed but the re-read is still None -> default_fx fails loud.
    monkeypatch.setattr(etoro.store, "fx_rate_eur",
                        lambda conn, cur, *, as_of: None)
    fx = production_fx(
        object(), as_of=_AS_OF, state_dir="STATE", clock=_Clock(),
        bar_fetcher=lambda pair, *, state_dir: "FRAME",
        bar_store=lambda *a, **k: 1)
    with pytest.raises(EtoroError, match="FX rate unavailable for USD"):
        fx(100.0, "USD")


def test_eur_never_fetches(monkeypatch):
    def fake_fx_rate_eur(conn, cur, *, as_of):  # pragma: no cover
        raise AssertionError("EUR must short-circuit before rate_source")

    monkeypatch.setattr(etoro.store, "fx_rate_eur", fake_fx_rate_eur)

    def boom(pair, *, state_dir):  # pragma: no cover
        raise AssertionError("EUR must not fetch")

    fx = production_fx(
        object(), as_of=_AS_OF, state_dir="STATE", clock=_Clock(),
        bar_fetcher=boom, bar_store=lambda *a, **k: 0)
    assert fx(100.0, "EUR") == 100.0
