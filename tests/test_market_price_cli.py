import json
from types import SimpleNamespace


class FakeMarketPrices:
    def __init__(self, status="SUCCEEDED"):
        self.status = status
        self.calls = []

    def refresh(self, conn, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(run_id=7, status=self.status, selected=20, completed=20,
                               remaining=0, ok=19, terminal=1, failed=0)

    def status_summary(self, conn, *, as_of):
        return {"schema_version": 1, "eligible": 20, "fresh": 19, "terminal": 1,
                "generated_at": as_of.isoformat()}


def test_market_price_refresh_forwards_resume_and_budget(
        tmp_path, monkeypatch, fixed_clock, capsys):
    from agentcy import cli

    fake = FakeMarketPrices()
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(cli, "_clock", lambda: fixed_clock)
    monkeypatch.setattr(cli, "_market_prices", lambda: fake)

    rc = cli.main([
        "market-data", "prices", "refresh", "--budget", "20", "--chunk-size", "5",
        "--resume", "7",
    ])

    assert rc == 0
    assert fake.calls[0]["budget"] == 20
    assert fake.calls[0]["chunk_size"] == 5
    assert fake.calls[0]["resume_run_id"] == 7
    assert json.loads(capsys.readouterr().out)["status"] == "SUCCEEDED"


def test_degraded_market_price_refresh_exits_one(
        tmp_path, monkeypatch, fixed_clock, capsys):
    from agentcy import cli

    fake = FakeMarketPrices(status="DEGRADED")
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(cli, "_clock", lambda: fixed_clock)
    monkeypatch.setattr(cli, "_market_prices", lambda: fake)

    assert cli.main(["market-data", "prices", "refresh", "--budget", "20"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "DEGRADED"


def test_market_price_status_writes_atomic_json(
        tmp_path, monkeypatch, fixed_clock, capsys):
    from agentcy import cli

    fake = FakeMarketPrices()
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(cli, "_clock", lambda: fixed_clock)
    monkeypatch.setattr(cli, "_market_prices", lambda: fake)
    output = tmp_path / "price-status.json"

    assert cli.main(["market-data", "prices", "status", "--out", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["fresh"] == 19
    assert not output.with_suffix(".json.tmp").exists()
    assert json.loads(capsys.readouterr().out)["eligible"] == 20
