"""`agentcy scout badge` records provided axes as review artifacts; omitted axes stay pending."""
from datetime import datetime, timezone
from agentcy import cli, clock as ck, db

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)


def test_badge_records_provided_axes_only(tmp_db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    rc = cli.main(["scout", "badge", "MSFT", "--moat", "confirmed", "--fad", "clear",
                   "--reason", "switching costs; real trend"])
    out = capsys.readouterr().out
    assert rc == 0 and "recorded" in out
    rows = {r["axis"]: r for r in db.fetch_scout_verdicts_current(tmp_db, "MSFT")}
    assert set(rows) == {"moat", "fad"}                   # mgmt/tier omitted -> pending, no row
    assert rows["moat"]["value"] == "confirmed"
    assert rows["moat"]["reason"] == "switching costs; real trend"


def test_badge_tier_correction_accepted(tmp_db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    rc = cli.main(["scout", "badge", "ACME", "--tier", "correction:Adjacent"])
    assert rc == 0
    rows = {r["axis"]: r for r in db.fetch_scout_verdicts_current(tmp_db, "ACME")}
    assert rows["tier"]["value"] == "correction:Adjacent"


def test_badge_rejects_bad_tier(tmp_db, monkeypatch):
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: ck.FixedClock(AS_OF))
    import pytest
    with pytest.raises(ValueError):
        cli.main(["scout", "badge", "ACME", "--tier", "Core"])   # must be ok|correction:<T>
