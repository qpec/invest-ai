"""benchmark.py — quarantined benchmark.db (tech-arch §4.6; contracts §3.8)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture()
def bench_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    return tmp_path


def test_migrate_creates_isolated_db_file(bench_dir):
    from agentcy import benchmark
    benchmark.migrate()
    assert (bench_dir / "benchmark.db").exists()
    assert not (bench_dir / "agentcy.db").exists()          # quarantine: never touches the main DB


def test_append_bars_is_insert_or_ignore_append_only(bench_dir):
    from agentcy import benchmark
    benchmark.migrate()
    rows = [
        {"bar_date": "2026-07-06", "sp500tr_usd": 14185.4, "usdeur": 0.859, "tr_eur": 12185.3, "fetched_at": "2026-07-08T08:30:00Z"},
        {"bar_date": "2026-07-07", "sp500tr_usd": 14262.9, "usdeur": 0.858, "tr_eur": 12237.6, "fetched_at": "2026-07-08T08:30:00Z"},
    ]
    assert benchmark.append_bars(rows, run_id=None) == 2
    # re-append same PKs -> ignored (append-only PK), no error, zero new
    assert benchmark.append_bars(rows, run_id=None) == 0


def test_series_eur_indexed_by_bar_date(bench_dir):
    from agentcy import benchmark
    benchmark.migrate()
    benchmark.append_bars([
        {"bar_date": "2026-07-06", "sp500tr_usd": 14185.4, "usdeur": 0.859, "tr_eur": 12185.3, "fetched_at": "2026-07-08T08:30:00Z"},
        {"bar_date": "2026-07-07", "sp500tr_usd": 14262.9, "usdeur": 0.858, "tr_eur": 12237.6, "fetched_at": "2026-07-08T08:30:00Z"},
    ], run_id=None)
    s = benchmark.series_eur("2026-07-06", "2026-07-07")
    assert list(s.index) == ["2026-07-06", "2026-07-07"]
    assert s.loc["2026-07-07"] == pytest.approx(12237.6)


def test_backup_to_and_integrity_check_are_data_free(bench_dir, tmp_path):
    from agentcy import benchmark
    benchmark.migrate()
    assert benchmark.integrity_check() is True              # returns a bool, not rows (jobs.backup handle)
    dest = tmp_path / "backup" / "benchmark.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    benchmark.backup_to(dest)
    assert dest.exists()


def test_append_bars_no_update_trigger_fires(bench_dir):
    import sqlite3
    from agentcy import benchmark
    benchmark.migrate()
    benchmark.append_bars([
        {"bar_date": "2026-07-07", "sp500tr_usd": 14262.9, "usdeur": 0.858, "tr_eur": 12237.6, "fetched_at": "2026-07-08T08:30:00Z"},
    ], run_id=None)
    conn = sqlite3.connect(bench_dir / "benchmark.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE benchmark_series SET tr_eur = 0 WHERE bar_date = '2026-07-07'")
    conn.close()
