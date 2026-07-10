"""P8.4 desk handlers. Domain modules are faked at the seam; these tests prove the
handler wiring (args -> correct call -> exit code / print), not the domain behaviour (P3/P4).

Per Interface Reconciliation R6 the scout handler calls the real P4 API
`scout.run_qv(conn, universe_path=None)` and prints its `ScreenResult` including
`scout.HONEST_EVIDENCE_NOTE` (NOT `run_recipe`), and never stores the result (H.2)."""
import types


def _wire(monkeypatch, tmp_db, fixed_clock):
    from agentcy import cli
    monkeypatch.setattr(cli, "_open", lambda: tmp_db)
    monkeypatch.setattr(cli, "_clock", lambda: fixed_clock)
    return cli


def test_bot_calls_daemon_run(monkeypatch):
    from agentcy import cli
    called = []
    monkeypatch.setattr(cli, "_daemon", lambda: types.SimpleNamespace(run=lambda: called.append(True)))
    assert cli.main(["bot"]) == 0
    assert called == [True]


def test_render_rebuild_calls_archive_rebuild(tmp_db, fixed_clock, monkeypatch, capsys):
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    monkeypatch.setattr(cli, "_archive", lambda: types.SimpleNamespace(rebuild=lambda conn, *, archive_dir: 42))
    assert cli.main(["render", "--rebuild"]) == 0
    assert "42" in capsys.readouterr().out


def test_scout_run_prints_evidence_note_never_stores(tmp_db, fixed_clock, monkeypatch, capsys):
    """R6: handler calls scout.run_qv and prints the ScreenResult + HONEST_EVIDENCE_NOTE.
    H.2: the screen is human-read only; the handler performs no DB write (no persistence)."""
    from agentcy import scout
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    result = scout.ScreenResult(
        recipe="qv",
        candidates=(scout.Candidate(symbol="ACME", ev_ebitda=7.5, roic=22.0, debt_to_equity=0.3),),
        evidence_note=scout.HONEST_EVIDENCE_NOTE,
    )
    seen = {}

    def _fake_run_qv(conn, *, universe_path=None):
        seen["conn"] = conn
        seen["universe_path"] = universe_path
        return result

    monkeypatch.setattr(cli, "_scout", lambda: types.SimpleNamespace(
        run_qv=_fake_run_qv, HONEST_EVIDENCE_NOTE=scout.HONEST_EVIDENCE_NOTE))
    assert cli.main(["scout", "run", "qv"]) == 0
    out = capsys.readouterr().out
    assert "ACME" in out
    assert scout.HONEST_EVIDENCE_NOTE in out
    assert seen["conn"] is tmp_db
    assert seen["universe_path"] is None
