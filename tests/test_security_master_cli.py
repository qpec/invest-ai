import csv
import json


def _inputs(tmp_path):
    universe = tmp_path / "universe.csv"
    with universe.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "name", "sector", "industry", "country", "market_cap",
                         "exchange", "currency"])
        writer.writerow(["ACME", "Acme Corporation", "Technology", "Software",
                         "United States", "Large Cap", "NMS", "USD"])
        writer.writerow(["DUTCH.AS", "Dutch Systems N.V.", "Technology", "Software",
                         "Netherlands", "Mid Cap", "AMS", "EUR"])
    sec = tmp_path / "company_tickers_exchange.json"
    sec.write_text(json.dumps({
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[1, "Acme Corporation", "ACME", "Nasdaq"]],
    }), encoding="utf-8")
    return universe, sec


def test_security_master_import_prints_json(tmp_path, monkeypatch, fixed_clock, capsys):
    from agentcy import cli

    universe, sec = _inputs(tmp_path)
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(cli, "_clock", lambda: fixed_clock)
    rc = cli.main([
        "security-master", "import", "--universe", str(universe),
        "--sec-exchange", str(sec), "--vintage", "2026-08-07",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["eligible"] == 2
    assert payload["input_rows"] == 2


def test_security_master_audit_writes_atomic_json(
        tmp_path, monkeypatch, fixed_clock, capsys):
    from agentcy import cli

    universe, sec = _inputs(tmp_path)
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(cli, "_clock", lambda: fixed_clock)
    assert cli.main([
        "security-master", "import", "--universe", str(universe),
        "--sec-exchange", str(sec), "--vintage", "2026-08-07",
    ]) == 0
    capsys.readouterr()
    output = tmp_path / "security-master-audit.json"
    assert cli.main(["security-master", "audit", "--out", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["eligible"] == 2
    assert not output.with_suffix(".json.tmp").exists()
