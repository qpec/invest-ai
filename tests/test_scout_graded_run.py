"""Stage-1 Scout entry point + CLI (design §4/§6): human-triggered graded run, results
human-read and NEVER persisted."""
import bz2
import hashlib
from datetime import datetime, timezone

import pandas as pd

from agentcy import db, config, clock as ck
from agentcy import scout
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)

CSV = (
    "symbol,name,sector,industry,country,market_cap\n"
    "MSFT,Microsoft,Technology,Software - Infrastructure,United States,large_cap\n"
    "VEEV,Veeva,Technology,Software - Application,United States,large_cap\n"
)

# RF6 baseline: latest within 90d of AS_OF, oldest a real ~1y anchor so shares_yoy is usable.
SHARE_INDEX = pd.to_datetime(["2025-06-20", "2025-12-20", "2026-06-20"])


def _universe(tmp_path):
    # tmp_db points AGENTCY_STATE_DIR at tmp_path, so the CLI's default universe lookup
    # (state_dir/universe/equities.bz2) resolves here — the run_graded tests also pass this
    # path explicitly, so both the explicit-path and default-path callers read the same file.
    path = tmp_path / "universe" / "equities.bz2"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bz2.compress(CSV.encode()))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(conn, sym, yf_statements, yf_series):
    store.store_statements(conn, sym, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, sym, yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_run_graded_returns_graded_names_and_never_persists(
        tmp_db, tmp_path, yf_statements, yf_series):
    path, sha = _universe(tmp_path)
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=ck.SystemClock())
    _seed(tmp_db, "MSFT", yf_statements, yf_series)
    _seed(tmp_db, "VEEV", yf_statements, yf_series)
    market = {"MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
              "VEEV": {"market_cap": 3.0e11, "total_debt": 60e9, "cash": 84e9}}

    result = scout.run_graded(tmp_db, universe_path=path, market_data=market, as_of=AS_OF)
    assert result.recipe == "grade"
    syms = {g.symbol for g in result.graded}
    assert syms == {"MSFT", "VEEV"}
    assert result.evidence_note == scout.HONEST_EVIDENCE_NOTE
    # H: never persisted as monitoring state
    assert db.fetch_watchlist(tmp_db) == []
    assert db.fetch_reports(tmp_db) == []


def test_run_graded_dilution_penalty_flows_through_the_entry_point(
        tmp_db, tmp_path, yf_statements):
    """RF6 — a diluting name (custom ~1y share series, shares_yoy_pct > 5) takes the -15
    dilution penalty end-to-end through run_graded: its composite is strictly below its
    identical-statement clean twin's and its GradedName note names the dilution."""
    csv = (
        "symbol,name,sector,industry,country,market_cap\n"
        "CLEAN,Clean,Technology,Software,United States,large_cap\n"
        "DILUT,Dilut,Technology,Software,United States,large_cap\n"
    )
    path = tmp_path / "equities.bz2"
    path.write_bytes(bz2.compress(csv.encode()))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=ck.SystemClock())
    pack = yf_statements("msft_statements")
    store.store_statements(tmp_db, "CLEAN", pack, run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_statements(tmp_db, "DILUT", pack, run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "CLEAN",
                       pd.Series([7.60e9, 7.50e9, 7.40e9], index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "DILUT",
                       pd.Series([7.20e9, 7.40e9, 7.60e9], index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")
    market = {"CLEAN": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
              "DILUT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9}}

    result = scout.run_graded(tmp_db, universe_path=path, market_data=market, as_of=AS_OF)
    by_sym = {g.symbol: g for g in result.graded}
    assert by_sym["CLEAN"].grade != "VETOED" and by_sym["DILUT"].grade != "VETOED"
    assert by_sym["DILUT"].composite < by_sym["CLEAN"].composite
    assert "dilut" in by_sym["DILUT"].note.lower()


def test_cli_scout_run_grade_prints(tmp_db, tmp_path, monkeypatch, capsys,
                                    yf_statements, yf_series):
    from agentcy import cli
    path, sha = _universe(tmp_path)
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=ck.SystemClock())
    _seed(tmp_db, "MSFT", yf_statements, yf_series)
    _seed(tmp_db, "VEEV", yf_statements, yf_series)

    # inject the open conn + a fixed clock + inline market data
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    import agentcy.scout as sc
    real = sc.run_graded
    monkeypatch.setattr(sc, "run_graded", lambda conn, **kw: real(
        conn, market_data={"MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
                           "VEEV": {"market_cap": 3.0e11, "total_debt": 60e9, "cash": 84e9}},
        **{k: v for k, v in kw.items() if k != "market_data"}))

    rc = cli.main(["scout", "run", "grade"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Core" in out and "promises nothing" in out.lower()


def test_run_graded_assembles_market_data_from_archive_when_none(
        tmp_db, tmp_path, yf_statements, yf_series):
    """market_data=None -> run_graded assembles it from the archive (populator design 5).
    A fully-seeded name (statements+shares+price) grades to a real letter, not INSUFFICIENT."""
    path, sha = _universe(tmp_path)
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=ck.SystemClock())
    for sym in ("MSFT", "VEEV"):
        _seed(tmp_db, sym, yf_statements, yf_series)
        pf = pd.DataFrame({"close": [500.0], "adj_close": [500.0], "dividend": [0.0],
                           "currency": ["USD"]}, index=pd.to_datetime(["2026-07-07"]))
        store.store_price_bars(tmp_db, sym, pf, run_id=None, fetched_at="2026-07-07T00:00:00Z")
    result = scout.run_graded(tmp_db, universe_path=path, market_data=None, as_of=AS_OF)
    by_sym = {g.symbol: g for g in result.graded}
    assert by_sym["MSFT"].grade in ("A", "B", "C", "D", "F")
    assert by_sym["MSFT"].composite is not None


def test_run_graded_absent_balance_sheet_degrades_to_insufficient_not_crash(
        tmp_db, tmp_path, yf_statements, yf_series):
    """market_data=None + a name whose balance sheet lacks Total Debt / Cash (realistic:
    banks, insurers, many ADRs) must degrade to INSUFFICIENT, never crash the whole run.
    The assembler emits total_debt/cash=None; value_metrics must return None (-> INSUFFICIENT)
    rather than raise on `ev = market_cap + total_debt - cash`."""
    path, sha = _universe(tmp_path)
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=ck.SystemClock())
    # MSFT: fully seeded, grades to a real letter. VEEV: balance sheet stripped of the two
    # market_data line items -> assembler yields market_cap present but total_debt/cash None.
    _seed(tmp_db, "MSFT", yf_statements, yf_series)
    pack = yf_statements("msft_statements")
    pack["balance"] = pack["balance"].drop(
        index=["Total Debt", "Cash And Cash Equivalents"])
    store.store_statements(tmp_db, "VEEV", pack, run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "VEEV", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    for sym in ("MSFT", "VEEV"):
        pf = pd.DataFrame({"close": [500.0], "adj_close": [500.0], "dividend": [0.0],
                           "currency": ["USD"]}, index=pd.to_datetime(["2026-07-07"]))
        store.store_price_bars(tmp_db, sym, pf, run_id=None, fetched_at="2026-07-07T00:00:00Z")

    # must NOT raise TypeError; the balance-less name degrades, the whole run survives
    result = scout.run_graded(tmp_db, universe_path=path, market_data=None, as_of=AS_OF)
    by_sym = {g.symbol: g for g in result.graded}
    assert by_sym["VEEV"].grade == "INSUFFICIENT"
    assert by_sym["MSFT"].grade in ("A", "B", "C", "D", "F")
