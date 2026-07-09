# tests/test_record_fixtures.py
"""tools/record_fixtures.py serialization helpers (offline; the fetch is desk-only, §13)."""
from __future__ import annotations

import json

import pandas as pd
import pytest


def test_frame_to_split_json_roundtrip(tmp_path):
    from tools import record_fixtures as rec
    frame = pd.DataFrame(
        {"Close": [1.0, 2.0], "Adj Close": [1.0, 2.0], "Dividends": [0.0, 0.5]},
        index=pd.to_datetime(["2026-07-06", "2026-07-07"]),
    )
    payload = rec.frame_to_fixture(frame, currency="USD")
    assert payload["currency"] == "USD"
    assert payload["index"] == ["2026-07-06", "2026-07-07"]
    assert "Close" in payload["columns"]
    # round-trips back to the same frame shape the conftest yf_frame loader expects
    idx = pd.to_datetime(payload["index"])
    back = pd.DataFrame(payload["data"], index=idx, columns=payload["columns"])
    assert list(back.columns) == payload["columns"] and len(back) == 2


def test_series_to_fixture_preserves_duplicates(tmp_path):
    from tools import record_fixtures as rec
    s = pd.Series([7.44e9, 7.43e9], index=pd.to_datetime(["2026-01-05", "2026-01-05"]))
    payload = rec.series_to_fixture(s)
    assert payload["index"] == ["2026-01-05", "2026-01-05"]      # duplicates kept (§7.4)
    assert payload["data"] == [7.44e9, 7.43e9]


def test_statements_to_fixture(tmp_path):
    from tools import record_fixtures as rec
    inc = pd.DataFrame({pd.Timestamp("2026-03-31"): [6.6e10]}, index=["Total Revenue"])
    payload = rec.statements_to_fixture({"income": inc})
    assert payload["income"]["columns"] == ["2026-03-31"]
    assert payload["income"]["index"] == ["Total Revenue"]


def test_write_fixture_emits_json_file(tmp_path):
    from tools import record_fixtures as rec
    rec.write_fixture(tmp_path, "demo", {"a": 1})
    assert json.loads((tmp_path / "demo.json").read_text()) == {"a": 1}
