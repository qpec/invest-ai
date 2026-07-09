"""Shared fixtures — contract per docs 00-contracts.md §4. Do not weaken the guards."""
from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

# --- (a) autouse no-network socket guard (tech-arch §13) ---------------------

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every test runs offline: any real socket connect raises immediately."""
    def _blocked(*_args, **_kwargs):
        raise RuntimeError(
            "network access attempted during a test (no-network guard, tech-arch §13); "
            "use tests/fixtures/yf/ recordings instead"
        )
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


# --- (b) fresh migrated SQLite in tmp_path ------------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Fresh, fully-migrated agentcy.db under tmp_path; AGENTCY_STATE_DIR points there
    (nothing may hardcode /var/lib at import time)."""
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    from agentcy import db
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    yield conn
    conn.close()


# --- (c) fixed clock ------------------------------------------------------------

@pytest.fixture()
def fixed_clock():
    """Deterministic Clock pinned to 2026-07-08 05:00 UTC (07:00 Europe/Amsterdam);
    injectable everywhere an as_of/clock parameter exists."""
    from agentcy.clock import FixedClock
    return FixedClock(datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc))


# --- golden-file comparison ------------------------------------------------------

GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.fixture()
def golden():
    """Byte-exact golden comparison (the no-LLM decision makes goldens the output-format
    spec). Record/update with UPDATE_GOLDEN=1; a missing golden is a failure otherwise."""
    def _assert(name: str, actual: str) -> None:
        path = GOLDEN_DIR / name
        if os.environ.get("UPDATE_GOLDEN") == "1":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8", newline="")
            return
        assert path.exists(), f"missing golden file {path}; run: UPDATE_GOLDEN=1 uv run pytest -q"
        expected = path.read_text(encoding="utf-8")
        assert actual == expected, f"golden mismatch: {name}"
    return _assert


# --- recorded yfinance fixtures ----------------------------------------------------

YF_FIXTURES = Path(__file__).parent / "fixtures" / "yf"


@pytest.fixture()
def yf_fixture():
    """Load a recorded yfinance response (tools/record_fixtures.py) as parsed JSON."""
    def _load(name: str):
        return json.loads((YF_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return _load

# --- phase-specific fixtures go below this line only ------------------------------

# --- P2: yfinance fixture -> pandas converters + sleep recorder -------------------

@pytest.fixture()
def yf_frame(yf_fixture):
    """Split-orient recorded frame -> (pd.DataFrame with DatetimeIndex, currency|None)."""
    import pandas as pd

    def _load(name: str):
        raw = yf_fixture(name)
        idx = pd.to_datetime(raw["index"]) if raw["index"] else []
        return pd.DataFrame(raw["data"], index=idx, columns=raw["columns"]), raw.get("currency")

    return _load


@pytest.fixture()
def yf_statements(yf_fixture):
    """Recorded statements pack -> {'income'|'balance'|'cashflow': DataFrame} (rows=line items, cols=period Timestamps)."""
    import pandas as pd

    def _load(name: str = "msft_statements"):
        raw = yf_fixture(name)
        return {
            stype: pd.DataFrame(part["data"], index=part["index"], columns=pd.to_datetime(part["columns"]))
            for stype, part in raw.items()
        }

    return _load


@pytest.fixture()
def yf_series(yf_fixture):
    """Recorded series (shares) -> pd.Series with DatetimeIndex, duplicates preserved."""
    import pandas as pd

    def _load(name: str = "msft_shares_full"):
        raw = yf_fixture(name)
        return pd.Series(raw["data"], index=pd.to_datetime(raw["index"]), dtype=float)

    return _load


@pytest.fixture()
def no_sleep(monkeypatch):
    """Record time.sleep durations instead of sleeping (pacing/backoff tests)."""
    import time as _time
    calls: list[float] = []
    monkeypatch.setattr(_time, "sleep", lambda s: calls.append(float(s)))
    return calls


# --- P3 domain fixtures -------------------------------------------------------------

@pytest.fixture()
def stamped():
    """Wrap a value as a FRESH/STALE/BOOTSTRAPPING Stamped for trigger-evaluator tests."""
    from datetime import datetime, timezone
    from agentcy.freshness import Stamped, DataState
    def _mk(value, state="fresh", note=None):
        return Stamped(value=value, fetched_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
                       state=DataState(state), note=note)
    return _mk


# --- P6: one seeded portfolio every jobs test shares -------------------------------

@pytest.fixture()
def seeded_portfolio(tmp_db, fixed_clock):
    """One snapshot (MSFT framework holding + cash), live intact thesis TH-MSFT-001 v1
    with one automated (margin_erosion) and one prompted (owner_attested_event, cadence
    event) trigger, symbol_map/designation, one fresh MSFT bar + USDEUR FX bar."""
    from agentcy import db, journal, register
    from agentcy.journal import EntryIn
    from agentcy.register import ThesisFields, TriggerSpec
    conn = tmp_db
    now = db.to_iso(fixed_clock.now())
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="test seed", actor="owner"), clock=fixed_clock)
    snap_id = db.append_snapshot(conn, as_of="2026-07-06T20:00:00Z", source="manual_export",
                                 cash_balance_eur=8000.0, created_at=now)
    db.append_positions(conn, snap_id, [dict(
        symbol="MSFT", yf_ticker="MSFT", instrument_type="stock", quantity=20.0,
        avg_open_price=300.0, native_currency="USD", mv_native=10000.0, mv_eur=8500.0,
        weight=0.515, leverage=1.0)])
    db.append_symbol_map(conn, symbol="MSFT", yf_ticker="MSFT", valid_from=now, journal_ref=je)
    db.append_designation(conn, symbol="MSFT", framework_status="framework",
                          valid_from=now, journal_ref=je)
    fields = ThesisFields(
        business_model_2s="Sells cloud infrastructure on subscription. Enterprise switching costs are the moat.",
        moat_types=("switching_costs",), moat_evidence="multi-year enterprise agreements",
        owner_earnings_json='{"fcf_ttm": 8.0e10}', owner_earnings_narrative="strong owner FCF",
        value_at_purchase=30.0, fair_band_low=25.0, fair_band_high=35.0,
        denominator_note=None, conviction="high", mgmt_trust="trusted_professional",
        mgmt_trust_note=None, circle_fit="core", circle_fit_note=None,
        ten_year_statement="Cloud consolidation runs a decade and the data moat compounds.",
        status_buy_flag=False, status_buy_note=None)
    trigs = [
        TriggerSpec(type="margin_erosion",
                    statement="If owner-FCF margin TTM < 20% for 2 consecutive quarters, the moat is leaking.",
                    metric="owner_fcf_margin_ttm", comparator="<", threshold=20.0,
                    moat_link="switching_costs", persistence="2_consecutive_quarters"),
        TriggerSpec(type="owner_attested_event",
                    statement="Has the CEO departed or announced departure?",
                    metric=None, comparator=None, threshold=None, moat_link=None,
                    persistence="single_observation", yes_means="fire"),
    ]
    tid = register.create_thesis(conn, ticker="MSFT", origin="gate", fields=fields,
                                 triggers=trigs, journal_ref=je, clock=fixed_clock)
    register.activate(conn, tid, cause="test seed", clock=fixed_clock)
    db.append_price_rows(conn, [
        dict(yf_ticker="MSFT", bar_date="2026-07-07", close=500.0, adj_close=500.0,
             dividend=0.0, currency="USD", fetched_at=now, run_id=None),
        dict(yf_ticker="USDEUR=X", bar_date="2026-07-07", close=0.85, adj_close=0.85,
             dividend=0.0, currency="EUR", fetched_at=now, run_id=None)])
    conn.commit()
    return {"conn": conn, "thesis_id": tid, "snapshot_id": snap_id, "journal_ref": je}
