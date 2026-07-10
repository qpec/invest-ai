"""Task 8 Piece B — `agentcy snapshot etoro [--dry-run] [--live]`.

Network-free by construction: `_etoro_client` is monkeypatched to a FakeClient and
`etoro.production_fx` is monkeypatched to a trivial deterministic fx, so no yfinance
call and no DB-price fetch ever happens. The real `fetch_etoro_snapshot` +
`ingest_snapshot` run against the tmp_db.
"""
import types

from agentcy import db


def _wire(monkeypatch, tmp_db, fixed_clock):
    from agentcy import cli
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: fixed_clock)
    return cli


class _FakeClient:
    def get_positions(self):
        return [
            {"symbol": "AAPL", "type": "Stocks", "units": 2.0, "invested": 400.0,
             "open_rate": 200.0, "open_date": "2024-06-01", "mv_native": 500.0,
             "pnl_native": 100.0, "leverage": 1.0, "currency": "USD"},
        ]

    def get_balances(self):
        return {"cash": 100.0, "currency": "USD"}


def _stub_fx_and_client(monkeypatch, cli):
    # trivial fx: USD->EUR at 0.9, else identity. No network, no DB price fetch.
    from agentcy.fetch import etoro
    monkeypatch.setattr(
        etoro, "production_fx",
        lambda conn, **kw: (lambda amount, ccy: amount * 0.9 if ccy == "USD" else amount))
    monkeypatch.setattr(cli, "_etoro_client", lambda api_key, user_key: _FakeClient())


def test_missing_env_keys_returns_1_and_writes_nothing(tmp_db, fixed_clock, monkeypatch, capsys):
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    monkeypatch.delenv("AGENTCY_ETORO_API_KEY", raising=False)
    monkeypatch.delenv("AGENTCY_ETORO_USER_KEY", raising=False)
    # if the branch tried to build a client it'd blow up — it must not get that far
    monkeypatch.setattr(cli, "_etoro_client",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")))
    rc = cli.main(["snapshot", "etoro"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "AGENTCY_ETORO" in err or "eToro" in err
    assert db.fetch_latest_snapshot(tmp_db) is None


def test_dry_run_prints_summary_and_writes_zero(tmp_db, fixed_clock, monkeypatch, capsys):
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    monkeypatch.setenv("AGENTCY_ETORO_API_KEY", "sekret-api")
    monkeypatch.setenv("AGENTCY_ETORO_USER_KEY", "sekret-user")
    _stub_fx_and_client(monkeypatch, cli)

    rc = cli.main(["snapshot", "etoro", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "AAPL" in out
    # cash 100 USD * 0.9 = 90 EUR shown in the summary
    assert "90" in out
    # secrets must NEVER be printed
    assert "sekret-api" not in out and "sekret-user" not in out
    # dry-run writes NOTHING
    assert db.fetch_latest_snapshot(tmp_db) is None


def test_non_dry_run_ingests_api_pull_and_mints(tmp_db, fixed_clock, monkeypatch, capsys):
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    monkeypatch.setenv("AGENTCY_ETORO_API_KEY", "sekret-api")
    monkeypatch.setenv("AGENTCY_ETORO_USER_KEY", "sekret-user")
    _stub_fx_and_client(monkeypatch, cli)

    # spy on the reconciliation producer to prove the etoro branch reuses the SAME
    # ingest+mint tail as import/enter (it delegates to the real mirror for ingest).
    from agentcy import mirror
    minted = []
    real_mint = mirror.mint_reconciliation_asks
    monkeypatch.setattr(
        mirror, "mint_reconciliation_asks",
        lambda conn, sid, ds, *, clock: (minted.append((sid, ds)),
                                         real_mint(conn, sid, ds, clock=clock))[1])

    rc = cli.main(["snapshot", "etoro"])
    assert rc == 0
    snap = db.fetch_latest_snapshot(tmp_db)
    assert snap is not None
    assert snap["source"] == "api_pull"
    out = capsys.readouterr().out
    assert "snapshot" in out.lower()
    # the reconciliation producer was invoked for the ingested snapshot's id
    assert len(minted) == 1 and minted[0][0] == snap["snapshot_id"]


def test_live_flag_is_accepted(tmp_db, fixed_clock, monkeypatch, capsys):
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    monkeypatch.setenv("AGENTCY_ETORO_API_KEY", "sekret-api")
    monkeypatch.setenv("AGENTCY_ETORO_USER_KEY", "sekret-user")
    _stub_fx_and_client(monkeypatch, cli)
    rc = cli.main(["snapshot", "etoro", "--dry-run", "--live"])
    assert rc == 0
