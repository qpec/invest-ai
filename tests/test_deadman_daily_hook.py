"""P8.3 (R4): the S2 dead-man ping is fired ONCE, inside ``jobs/daily.main`` after a
SUCCESSFUL sweep — never on a failed run, and never from the CLI.

R4 keeps a single ping implementation (``agentcy/deadman.py``, exercised directly in
``test_deadman.py``). What was untested — and is the genuine P8.3 artifact — is the
*hook*: ``daily.main`` calls ``deadman.ping(conn)`` iff ``sweep_and_run`` returns 0, and
``cli._cmd_run`` forwards to ``main`` without pinging (the job owns the ping, the CLI
never does). These tests lock that contract.
"""
from datetime import datetime, timezone

from agentcy import db, deadman
from agentcy.clock import FixedClock
from agentcy.jobs import daily, runner


def test_daily_main_pings_once_after_a_successful_sweep(seeded_portfolio, tmp_path, monkeypatch):
    conn = seeded_portfolio["conn"]
    conn.commit()
    conn.close()                                         # daily.main opens its own connection
    clock = FixedClock(datetime(2026, 7, 10, 5, 0, tzinfo=timezone.utc))  # Fri: a full letter
    monkeypatch.setattr(daily, "refresh_prices",
                        lambda conn, tickers, **kw: {"MSFT": "ok", "USDEUR=X": "ok"})
    pings = []
    monkeypatch.setattr(deadman, "ping", lambda conn: pings.append(conn))
    rc = daily.main(clock=clock, state_dir=tmp_path)
    assert rc == 0
    assert len(pings) == 1                               # exactly one ping per successful daily run


def test_daily_main_does_not_ping_when_the_sweep_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    conn = db.open_db(tmp_path)
    db.migrate(conn)
    conn.close()
    clock = FixedClock(datetime(2026, 7, 10, 5, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(runner, "sweep_and_run", lambda *a, **k: 1)   # a failed sweep
    pings = []
    monkeypatch.setattr(deadman, "ping", lambda conn: pings.append(conn))
    rc = daily.main(clock=clock, state_dir=tmp_path)
    assert rc == 1
    assert pings == []                                   # a failed run must NOT report itself alive


def test_cli_run_daily_never_pings_itself(tmp_path, monkeypatch):
    """R1/R4: the CLI forwards to jobs.daily.main and does not fire the ping itself."""
    from agentcy import cli
    monkeypatch.setenv("AGENTCY_STATE_DIR", str(tmp_path))
    called = {"main": 0}

    def fake_main(*, clock, state_dir):
        called["main"] += 1
        return 0
    monkeypatch.setattr(cli, "_job_module", lambda name: type("M", (), {"main": staticmethod(fake_main)}))

    def _never(conn):
        raise AssertionError("the CLI must not ping — jobs/daily.main owns the ping (R4)")
    monkeypatch.setattr(deadman, "ping", _never)
    assert cli.main(["run", "daily"]) == 0
    assert called["main"] == 1
