import pytest


def test_parser_covers_the_section_10_surface():
    from agentcy.cli import build_parser
    p = build_parser()
    sub = next(a for a in p._actions if hasattr(a, "choices") and a.choices)
    assert set(sub.choices) == {
        "run", "bot", "gate", "scout", "watchlist", "snapshot", "journal",
        "thesis", "config", "absence", "ask", "event", "render",
    }


def test_run_job_choices_are_exactly_the_four_scheduled_jobs():
    from agentcy.cli import build_parser
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "backup"])  # NOT on the §10 run surface
    args = build_parser().parse_args(["run", "daily"])
    assert args.job == "daily" and args.handler == "run"


def test_unwired_handler_exits_2(monkeypatch):
    from agentcy import cli
    monkeypatch.setattr(cli, "_HANDLERS", {})
    assert cli.main(["run", "daily"]) == 2


def test_no_command_exits_2():
    from agentcy import cli
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2


# --- P8.2: `agentcy run {daily,weekly,quarterly,event}` job dispatch ---------------
# Contract per Interface Reconciliation R1: the CLI calls jobs.<job>.main(clock=, state_dir=)
# and uses the returned int VERBATIM as the process exit code. There is no
# run(conn,*,clock)->str, no CLI-opened connection, no status-string branch, no CLI ping.


def _wire_run(monkeypatch):
    from agentcy import cli, db
    monkeypatch.setattr(cli, "_clock", lambda: "CLK")
    monkeypatch.setattr(db, "state_dir", lambda: "SD")
    return cli


def test_run_dispatches_to_the_job_module_main(monkeypatch):
    import types
    cli = _wire_run(monkeypatch)
    calls = []
    fake = types.SimpleNamespace(main=lambda **kw: calls.append(kw) or 0)
    monkeypatch.setattr(cli, "_job_module", lambda name: {"weekly": fake}[name])
    assert cli.main(["run", "weekly"]) == 0
    assert calls == [{"clock": "CLK", "state_dir": "SD"}]


def test_run_returns_the_jobs_exit_code_verbatim(monkeypatch):
    # R1: main returns 0 (ok) or 1 (degraded/failed); the CLI passes it straight through,
    # it does NOT branch on a status string.
    import types
    cli = _wire_run(monkeypatch)
    fake = types.SimpleNamespace(main=lambda **kw: 1)
    monkeypatch.setattr(cli, "_job_module", lambda name: fake)
    assert cli.main(["run", "quarterly"]) == 1


def test_run_daily_ok_exits_0(monkeypatch):
    import types
    cli = _wire_run(monkeypatch)
    fake = types.SimpleNamespace(main=lambda **kw: 0)
    monkeypatch.setattr(cli, "_job_module", lambda name: fake)
    assert cli.main(["run", "daily"]) == 0


def test_run_job_exception_propagates_uncaught(monkeypatch):
    # degraded-letter-before-re-raise: the job already enqueued the letter; the re-raise
    # must reach systemd so OnFailure= fires (§1.3). The CLI must not swallow it.
    import types
    cli = _wire_run(monkeypatch)
    def boom(**kw):
        raise RuntimeError("wedged HTTPS call")
    monkeypatch.setattr(cli, "_job_module", lambda name: types.SimpleNamespace(main=boom))
    with pytest.raises(RuntimeError, match="wedged"):
        cli.main(["run", "event"])
