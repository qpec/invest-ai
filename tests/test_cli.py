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
