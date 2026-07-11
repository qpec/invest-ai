"""`agentcy scout review render` prints the Stage-2 annotated shortlist and writes NO monitoring
row (review artifact only). Reuses the Task 6 universe/seed idiom; verdicts recorded via the
review-artifact store flow through into the badge column + one-band adjustment."""
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


def _wire(tmp_db, tmp_path, monkeypatch, yf_statements, yf_series):
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


def test_review_render_cli_writes_no_monitoring(tmp_db, tmp_path, monkeypatch, capsys,
                                                yf_statements, yf_series):
    _wire(tmp_db, tmp_path, monkeypatch, yf_statements, yf_series)
    db.append_scout_verdict(tmp_db, ticker="MSFT", axis="fad", value="flag",
                            reason="test", recorded_at="2026-07-08T05:00:00Z")

    rc = cli.main(["scout", "review", "render"])
    out = capsys.readouterr().out
    assert rc == 0 and "Stage-2 annotated shortlist" in out
    # the recorded fad flag rode through into the annotated table
    assert "MSFT" in out and "fad[x]" in out and "demote one band" in out
    # NEVER a monitoring write - only the pre-seeded review artifact exists
    assert db.fetch_reports(tmp_db) == []
    assert db.fetch_watchlist(tmp_db) == []


def test_review_render_cli_pending_when_no_verdicts(tmp_db, tmp_path, monkeypatch, capsys,
                                                    yf_statements, yf_series):
    _wire(tmp_db, tmp_path, monkeypatch, yf_statements, yf_series)

    rc = cli.main(["scout", "review", "render"])
    out = capsys.readouterr().out
    assert rc == 0 and "pending" in out.lower()
    assert db.fetch_reports(tmp_db) == []
    assert db.fetch_scout_verdicts_current(tmp_db) == []
