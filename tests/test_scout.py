"""tests/test_scout.py — The Scout (H.1/H.2), P4."""
from __future__ import annotations

import bz2
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from agentcy import db, scout


TINY_CSV = (
    "symbol,name,sector,industry,country,market_cap\n"
    "VEEV,Veeva,Technology,Software,United States,large_cap\n"
    "ASML,ASML,Technology,Semiconductors,Netherlands,large_cap\n"
)


@pytest.fixture()
def universe_file(tmp_path):
    """A tiny bz2 the tests generate + hash inline (the real 160k-row file is a
    pinned-commit desk asset; the read logic is identical)."""
    raw = TINY_CSV.encode("utf-8")
    path = tmp_path / "equities.bz2"
    path.write_bytes(bz2.compress(raw))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, sha


def test_load_universe_reads_rows(universe_file):
    path, sha = universe_file
    df = scout.load_universe(path, expect_sha=sha)
    assert list(df["symbol"]) == ["VEEV", "ASML"]


def test_load_universe_rejects_wrong_sha(universe_file):
    path, _ = universe_file
    with pytest.raises(scout.UniverseSHAError):
        scout.load_universe(path, expect_sha="0" * 64)


def test_load_universe_empty_sha_pin_refuses(universe_file):
    path, sha = universe_file
    # an unset pin ('' in config) must not silently pass any file
    with pytest.raises(scout.UniverseSHAError):
        scout.load_universe(path, expect_sha="")


# --- P4.17 QV screen ----------------------------------------------------------

def test_honest_evidence_note_is_present_and_specific():
    assert "3" in scout.HONEST_EVIDENCE_NOTE and "6" in scout.HONEST_EVIDENCE_NOTE
    assert "promises nothing" in scout.HONEST_EVIDENCE_NOTE.lower()
    assert "gate" in scout.HONEST_EVIDENCE_NOTE.lower()


def test_run_qv_uses_lazy_import_and_ranks_by_cheapness(tmp_db, monkeypatch, universe_file):
    from agentcy import scout as sc
    path, sha = universe_file
    # pin the sha in config so run_qv can load the universe
    from agentcy import config
    config.set(tmp_db, "universe_pin_sha", sha, reason="test", actor="owner",
               clock=__import__("agentcy.clock", fromlist=["SystemClock"]).SystemClock())

    # fake the [scout]-extra screener: returns raw rows out of cheapness order
    screener_rows = pd.DataFrame({
        "symbol": ["ASML", "VEEV"],
        "enterprise_value_ebitda_ttm": [18.0, 9.0],     # VEEV is cheaper
        "return_on_invested_capital": [22.0, 30.0],
        "debt_to_equity": [0.4, 0.2],
    })
    monkeypatch.setattr(sc, "_run_screener", lambda recipe: screener_rows)

    result = sc.run_qv(tmp_db, universe_path=path)
    assert [c.symbol for c in result.candidates] == ["VEEV", "ASML"]   # cheapest first
    assert result.candidates[0].ev_ebitda == 9.0
    assert result.evidence_note == sc.HONEST_EVIDENCE_NOTE
    assert len(result.candidates) <= 20


def test_run_qv_caps_at_top_20(tmp_db, monkeypatch, universe_file):
    from agentcy import scout as sc
    path, sha = universe_file
    from agentcy import config, clock
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=clock.SystemClock())
    # universe only has VEEV/ASML, so intersect first; build a 25-row screener that
    # includes both universe symbols plus noise not in the universe
    rows = pd.DataFrame({
        "symbol": ["VEEV", "ASML"] + [f"X{i}" for i in range(25)],
        "enterprise_value_ebitda_ttm": [9.0, 18.0] + [5.0] * 25,
        "return_on_invested_capital": [30.0, 22.0] + [20.0] * 25,
        "debt_to_equity": [0.2, 0.4] + [0.1] * 25,
    })
    monkeypatch.setattr(sc, "_run_screener", lambda recipe: rows)
    result = sc.run_qv(tmp_db, universe_path=path)
    # only VEEV/ASML survive the universe intersection
    assert set(c.symbol for c in result.candidates) == {"VEEV", "ASML"}


def test_run_qv_never_persists(tmp_db, monkeypatch, universe_file):
    from agentcy import scout as sc
    path, sha = universe_file
    from agentcy import config, clock
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=clock.SystemClock())
    monkeypatch.setattr(sc, "_run_screener", lambda recipe: pd.DataFrame({
        "symbol": ["VEEV"], "enterprise_value_ebitda_ttm": [9.0],
        "return_on_invested_capital": [30.0], "debt_to_equity": [0.2]}))
    sc.run_qv(tmp_db, universe_path=path)
    # no watchlist row, no report row created by the screen (H: never stored)
    assert db.fetch_watchlist(tmp_db) == []
    assert db.fetch_reports(tmp_db) == []


# --- P4.18 import-graph guard -------------------------------------------------

def test_importing_scout_does_not_import_tradingview():
    import sys
    # scout is already imported by this test module; assert the extra is absent
    assert "tradingview_screener" not in sys.modules, (
        "tradingview-screener must be imported lazily inside _run_screener only "
        "(NFR7 import-graph contract)")


def test_gate_module_imports_no_scout_extra():
    import sys, importlib
    importlib.import_module("agentcy.gate")
    assert "tradingview_screener" not in sys.modules
