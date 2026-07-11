"""agentcy run populate CLI wiring (populator design 7). Forwards clock/state_dir + the
optional --minutes/--budget to jobs.populate.main; returns its int verbatim."""
from agentcy import cli


def test_run_populate_forwards_budget(monkeypatch):
    seen = {}
    class _Fake:
        def main(self, **kw):
            seen.update(kw); return 0
    monkeypatch.setattr(cli, "_job_module", lambda name: _Fake() if name == "populate" else None)
    rc = cli.main(["run", "populate", "--budget", "50"])
    assert rc == 0
    assert seen["budget"] == 50 and seen["minutes"] is None


def test_run_populate_forwards_minutes(monkeypatch):
    seen = {}
    class _Fake:
        def main(self, **kw):
            seen.update(kw); return 1
    monkeypatch.setattr(cli, "_job_module", lambda name: _Fake())
    rc = cli.main(["run", "populate", "--minutes", "30"])
    assert rc == 1
    assert seen["minutes"] == 30 and seen["budget"] is None


def test_run_populate_defaults_both_none(monkeypatch):
    seen = {}
    class _Fake:
        def main(self, **kw):
            seen.update(kw); return 0
    monkeypatch.setattr(cli, "_job_module", lambda name: _Fake())
    cli.main(["run", "populate"])
    assert seen["budget"] is None and seen["minutes"] is None


def test_run_daily_still_works(monkeypatch):
    """The existing run jobs must not regress: daily takes no budget/minutes kwargs."""
    seen = {}
    class _Fake:
        def main(self, **kw):
            seen.update(kw); return 0
    monkeypatch.setattr(cli, "_job_module", lambda name: _Fake())
    cli.main(["run", "daily"])
    assert "budget" not in seen and "minutes" not in seen
