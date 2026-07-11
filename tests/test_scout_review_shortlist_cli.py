"""`agentcy scout shortlist` prints a claudeclaw-parseable dossier + the honest note; no DB write."""
import bz2
import hashlib
from datetime import datetime, timezone

from agentcy import cli, config, clock as ck, db
from agentcy.fetch import store

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)
CSV = ("symbol,name,sector,industry,country,market_cap\n"
       "MSFT,Microsoft,Technology,Software,United States,large_cap\n"
       "VEEV,Veeva,Technology,Health Care Technology,United States,large_cap\n")


def _universe(tmp_path):
    path = tmp_path / "universe" / "equities.bz2"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bz2.compress(CSV.encode()))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(conn, sym, yf_statements, yf_series):
    store.store_statements(conn, sym, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, sym, yf_series("msft_shares_full"), fetched_at="2026-07-01T00:00:00Z")


def test_scout_shortlist_prints_dossier(tmp_db, tmp_path, monkeypatch, capsys,
                                        yf_statements, yf_series):
    path, sha = _universe(tmp_path)
    config.set(tmp_db, "universe_pin_sha", sha, reason="t", actor="owner", clock=ck.SystemClock())
    _seed(tmp_db, "MSFT", yf_statements, yf_series)
    _seed(tmp_db, "VEEV", yf_statements, yf_series)
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    import agentcy.scout as sc
    real = sc.run_graded
    monkeypatch.setattr(sc, "run_graded", lambda conn, **kw: real(
        conn, market_data={"MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
                           "VEEV": {"market_cap": 3.0e11, "total_debt": 60e9, "cash": 84e9}},
        **{k: v for k, v in kw.items() if k != "market_data"}))

    rc = cli.main(["scout", "shortlist"])
    out = capsys.readouterr().out
    assert rc == 0
    # claudeclaw-parseable header line + the four questions + doc pointer + honest note
    assert "| grade " in out and "| tier " in out
    assert "moat:" in out and "mgmt:" in out and "fad:" in out and "tier:" in out
    assert "10-K MD&A" in out
    assert "promises nothing" in out.lower()
    # H: no monitoring state written
    assert db.fetch_watchlist(tmp_db) == []
    assert db.fetch_reports(tmp_db) == []
    assert db.fetch_scout_verdicts_current(tmp_db) == []
