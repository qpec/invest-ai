from pathlib import Path

import pandas as pd

from agentcy.fetch import yf as fetch_yf


def _batch_frame():
    index = pd.to_datetime(["2026-08-05", "2026-08-06"])
    columns = pd.MultiIndex.from_product([
        ["ACME", "SPLT", "BAD"],
        ["Close", "Adj Close", "Dividends", "Stock Splits"],
    ])
    frame = pd.DataFrame(index=index, columns=columns, dtype=float)
    frame[("ACME", "Close")] = [10.0, 11.0]
    frame[("ACME", "Adj Close")] = [9.5, 10.5]
    frame[("ACME", "Dividends")] = [0.0, 0.25]
    frame[("ACME", "Stock Splits")] = [0.0, 0.0]
    frame[("SPLT", "Close")] = [20.0, 10.0]
    frame[("SPLT", "Adj Close")] = [10.0, 10.0]
    frame[("SPLT", "Dividends")] = [0.0, 0.0]
    frame[("SPLT", "Stock Splits")] = [2.0, 0.0]
    frame[("BAD", "Close")] = [0.0, 0.0]
    frame[("BAD", "Adj Close")] = [0.0, 0.0]
    frame[("BAD", "Dividends")] = [0.0, 0.0]
    frame[("BAD", "Stock Splits")] = [0.0, 0.0]
    return frame


def test_batch_normalizes_each_symbol_and_keeps_reported_splits(monkeypatch):
    monkeypatch.setattr(fetch_yf, "_raw_history_batch",
                        lambda symbols, period: _batch_frame())
    monkeypatch.setattr(fetch_yf, "_paced_call", lambda state_dir, fn: fn())

    frames, failures = fetch_yf.fetch_daily_bars_batch(
        ["ACME", "SPLT", "BAD"],
        currencies={"ACME": "USD", "SPLT": "USD", "BAD": "USD"},
        state_dir=Path("/tmp/unused"),
    )

    assert set(frames) == {"ACME", "SPLT"}
    assert failures == {"BAD": "NON_POSITIVE_CLOSE"}
    assert list(frames["ACME"].columns) == [
        "close", "adj_close", "dividend", "split", "currency"
    ]
    assert frames["SPLT"].loc[pd.Timestamp("2026-08-05"), "split"] == 2.0


def test_batch_rejects_symbol_without_currency(monkeypatch):
    monkeypatch.setattr(fetch_yf, "_raw_history_batch",
                        lambda symbols, period: _batch_frame().loc[:, ["ACME"]])
    monkeypatch.setattr(fetch_yf, "_paced_call", lambda state_dir, fn: fn())

    frames, failures = fetch_yf.fetch_daily_bars_batch(
        ["ACME"], currencies={}, state_dir=Path("/tmp/unused")
    )

    assert frames == {}
    assert failures == {"ACME": "MISSING_CURRENCY"}


def test_empty_batch_is_fail_loud(monkeypatch):
    monkeypatch.setattr(fetch_yf, "_raw_history_batch",
                        lambda symbols, period: pd.DataFrame())
    monkeypatch.setattr(fetch_yf, "_paced_call", lambda state_dir, fn: fn())

    try:
        fetch_yf.fetch_daily_bars_batch(
            ["ACME"], currencies={"ACME": "USD"}, state_dir=Path("/tmp/unused")
        )
    except fetch_yf.FetchFailed as error:
        assert "empty price batch" in str(error)
    else:
        raise AssertionError("empty batch must raise FetchFailed")
