from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from agentcy import db
from agentcy.fetch import yf as fetch_yf


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def _eligible(conn):
    conn.execute(
        "INSERT INTO security_master_run"
        " (source_vintage, input_hash, started_at, finished_at, status, input_rows,"
        " eligible_rows, ineligible_rows, review_rows) VALUES"
        " ('v1', 'hash', '2026-08-07T10:00:00Z', '2026-08-07T10:01:00Z',"
        " 'SUCCEEDED', 2, 2, 0, 0)"
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for cik, symbol, currency in ((1, "ACME", "USD"), (2, "DUTCH.AS", "EUR")):
        conn.execute(
            "INSERT INTO security_observation"
            " (run_id, security_key, cik, symbol, name, country, exchange, currency,"
            " instrument_type, eligibility, reason_code, source, source_hash, observed_at)"
            " VALUES (?, ?, ?, ?, ?, 'US', 'Nasdaq', ?, 'ORDINARY_SHARE', 'ELIGIBLE',"
            " 'PRIMARY_ORDINARY_SHARE', 'test', ?, '2026-08-07T10:00:00Z')",
            (run_id, f"cik:{cik:010d}", f"{cik:010d}", symbol, symbol, currency,
             f"hash-{symbol}"),
        )


def _frame(symbol):
    return pd.DataFrame({
        "close": [10.0], "adj_close": [9.5], "dividend": [0.0],
        "split": [0.0], "currency": ["EUR" if symbol.endswith(".AS") else "USD"],
    }, index=pd.to_datetime(["2026-08-06"]))


def _fetch(symbols, *, currencies, state_dir, period="10d"):
    return ({symbol: _frame(symbol) for symbol in symbols}, {})


def test_payload_hash_is_deterministic():
    from agentcy.market_prices import observation_hash

    row = dict(security_key="cik:0000000001", provider="yahoo",
               provider_symbol="ACME", bar_date="2026-08-06", raw_close=10.0,
               adjusted_close=9.5, dividend=0.0, split_ratio=None, currency="USD")
    assert observation_hash(row) == observation_hash(dict(reversed(list(row.items()))))


def test_partial_refresh_resumes_and_only_then_promotes(tmp_db):
    from agentcy.market_prices import refresh

    _eligible(tmp_db)
    first = refresh(tmp_db, fetch_batch=_fetch, state_dir=Path("/tmp/unused"), now=NOW,
                    scheduled_for="2026-08-07", budget=1, chunk_size=1)
    assert first.status == "RUNNING"
    assert first.completed == 1
    assert first.remaining == 1
    assert tmp_db.execute("SELECT COUNT(*) FROM v_current_market_price").fetchone()[0] == 0

    second = refresh(tmp_db, fetch_batch=_fetch, state_dir=Path("/tmp/unused"), now=NOW,
                     scheduled_for="2026-08-07", budget=10, chunk_size=1,
                     resume_run_id=first.run_id)
    assert second.status == "SUCCEEDED"
    assert second.remaining == 0
    assert tmp_db.execute("SELECT COUNT(*) FROM v_current_market_price").fetchone()[0] == 2


def test_resume_skips_completed_security(tmp_db):
    from agentcy.market_prices import refresh

    _eligible(tmp_db)
    calls = []

    def recording(symbols, **kwargs):
        calls.extend(symbols)
        return _fetch(symbols, **kwargs)

    first = refresh(tmp_db, fetch_batch=recording, state_dir=Path("/tmp/unused"), now=NOW,
                    scheduled_for="2026-08-07", budget=1, chunk_size=1)
    refresh(tmp_db, fetch_batch=recording, state_dir=Path("/tmp/unused"), now=NOW,
            scheduled_for="2026-08-07", budget=10, chunk_size=1,
            resume_run_id=first.run_id)
    assert sorted(calls) == ["ACME", "DUTCH.AS"]


def test_rate_limit_degrades_without_promoting(tmp_db):
    from agentcy.market_prices import refresh

    _eligible(tmp_db)

    def limited(*args, **kwargs):
        raise fetch_yf.RateLimited("test limit")

    summary = refresh(tmp_db, fetch_batch=limited, state_dir=Path("/tmp/unused"),
                      now=NOW, scheduled_for="2026-08-07", budget=2, chunk_size=2)
    assert summary.status == "DEGRADED"
    assert tmp_db.execute("SELECT COUNT(*) FROM v_current_market_price").fetchone()[0] == 0


def test_freshness_refuses_price_older_than_45_days():
    from agentcy.market_prices import freshness_status

    assert freshness_status("2026-08-06", NOW) == "FRESH"
    assert freshness_status("2026-06-01", NOW) == "STALE"


def test_refresh_persists_latest_bar_and_historical_split_events(tmp_db):
    from agentcy.market_prices import refresh

    _eligible(tmp_db)

    def history(symbols, **kwargs):
        frames = {}
        for symbol in symbols:
            frames[symbol] = pd.DataFrame({
                "close": [20.0, 10.0, 11.0], "adj_close": [10.0, 10.0, 11.0],
                "dividend": [0.0, 0.0, 0.0], "split": [0.0, 2.0, 0.0],
                "currency": ["USD", "USD", "USD"],
            }, index=pd.to_datetime(["2026-01-01", "2026-02-01", "2026-08-06"]))
        return frames, {}

    refresh(tmp_db, fetch_batch=history, state_dir=Path("/tmp/unused"), now=NOW,
            scheduled_for="2026-08-07", budget=2, chunk_size=2)
    rows = tmp_db.execute(
        "SELECT bar_date, split_ratio FROM market_price_observation"
        " WHERE provider_symbol='ACME' ORDER BY bar_date"
    ).fetchall()
    assert [(row["bar_date"], row["split_ratio"]) for row in rows] == [
        ("2026-02-01", 2.0), ("2026-08-06", None)
    ]
