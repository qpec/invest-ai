"""Per-ticker fetch+store unit (populator design 3/6). Fake fetch layer, no network."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from agentcy import db, populate
from agentcy.fetch import store
from agentcy.fetch.yf import FetchFailed, RateLimited

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
FETCHED_AT = "2026-07-08T00:00:00Z"


class _FakeYf:
    """Stand-in for the fetch/yf.py door; the populate loop calls populate.yf.*"""
    def __init__(self, statements=None, shares=None, bars=None, raises=None):
        self._statements, self._shares, self._bars, self._raises = statements, shares, bars, raises

    def fetch_statements(self, t, *, state_dir):
        if isinstance(self._raises, dict) and "statements" in self._raises:
            raise self._raises["statements"]
        return self._statements

    def fetch_shares_full(self, t, *, state_dir):
        return self._shares

    def fetch_daily_bars(self, t, *, state_dir):
        return self._bars


def _bars():
    return pd.DataFrame(
        {"close": [500.0], "adj_close": [500.0], "dividend": [0.0], "currency": ["USD"]},
        index=pd.to_datetime(["2026-07-07"]))


def test_fetch_one_ok_persists_all_three_sources(tmp_db, monkeypatch, yf_statements, yf_series, tmp_path):
    fake = _FakeYf(statements=yf_statements("msft_statements"),
                   shares=yf_series("msft_shares_full"), bars=_bars())
    monkeypatch.setattr(populate, "yf", fake)
    outcome = populate.fetch_one(tmp_db, "MSFT", run_id=None, fetched_at=FETCHED_AT,
                                 state_dir=tmp_path)
    assert outcome == populate.Outcome.OK
    assert len(db.fetch_statement_periods(tmp_db, "MSFT", "income")) >= 4
    assert db.fetch_shares_raw(tmp_db, "MSFT")
    assert db.fetch_v_price(tmp_db, "MSFT")


def test_fetch_one_maps_fetchfailed_to_failed(tmp_db, monkeypatch, tmp_path):
    fake = _FakeYf(raises={"statements": FetchFailed("empty")})
    monkeypatch.setattr(populate, "yf", fake)
    outcome = populate.fetch_one(tmp_db, "X", run_id=None, fetched_at=FETCHED_AT, state_dir=tmp_path)
    assert outcome == populate.Outcome.FAILED


def test_fetch_one_maps_ratelimited_to_rate_limited(tmp_db, monkeypatch, tmp_path):
    fake = _FakeYf(raises={"statements": RateLimited("throttled")})
    monkeypatch.setattr(populate, "yf", fake)
    outcome = populate.fetch_one(tmp_db, "X", run_id=None, fetched_at=FETCHED_AT, state_dir=tmp_path)
    assert outcome == populate.Outcome.RATE_LIMITED
