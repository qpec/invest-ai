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


# --- P8.5 gate start/resume/--backfill (R6: P4 signatures, FR9 ask_owner seam) ---

def test_gate_start_passes_ticker_mode_ask_owner_clock(tmp_db, fixed_clock, monkeypatch):
    """R6: gate.start(conn, ticker=.., mode=.., ask_owner=ao, clock=..). FR9: the
    owner-field seam is an ask_owner callable (input()-driven), never a flag."""
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    calls = {}
    fake = types.SimpleNamespace(
        start=lambda conn, *, ticker, mode, ask_owner, clock:
            calls.update(conn=conn, ticker=ticker, mode=mode, ao=ask_owner, clock=clock),
        resume=lambda conn, *, session_id, ask_owner, clock:
            calls.update(resumed=session_id),
    )
    monkeypatch.setattr(cli, "_gate", lambda: fake)
    assert cli.main(["gate", "start", "CRWD"]) == 0
    assert (calls["conn"], calls["ticker"], calls["mode"]) == (tmp_db, "CRWD", "gate")
    assert calls["clock"] is fixed_clock
    assert callable(calls["ao"])
    assert cli.main(["gate", "start", "ASML", "--backfill"]) == 0
    assert calls["mode"] == "backfill"


def test_gate_resume_passes_active_session_id(tmp_db, fixed_clock, monkeypatch):
    """R6: gate.resume(conn, session_id=<active session id>, ask_owner=ao, clock=..).
    The active session id comes from db.fetch_active_gate_session (a Row -> session_id)."""
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    got = {}
    monkeypatch.setattr("agentcy.db.fetch_active_gate_session",
                        lambda conn, *a, **k: {"session_id": 7, "ticker": "NET"})
    fake = types.SimpleNamespace(
        start=lambda conn, **k: None,
        resume=lambda conn, *, session_id, ask_owner, clock:
            got.update(session_id=session_id, ao=ask_owner, clock=clock),
    )
    monkeypatch.setattr(cli, "_gate", lambda: fake)
    assert cli.main(["gate", "resume"]) == 0
    assert got["session_id"] == 7
    assert got["clock"] is fixed_clock
    assert callable(got["ao"])


def test_gate_resume_no_active_session_exits_1(tmp_db, fixed_clock, monkeypatch, capsys):
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    monkeypatch.setattr("agentcy.db.fetch_active_gate_session", lambda conn, *a, **k: None)
    monkeypatch.setattr(cli, "_gate", lambda: types.SimpleNamespace(
        resume=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not resume"))))
    assert cli.main(["gate", "resume"]) == 1
    assert "no active gate session" in capsys.readouterr().err


def test_ask_owner_from_input_reads_input(monkeypatch):
    """FR9 seam: _ask_owner_from_input returns an AskOwner (prompt, options=None) -> str
    that reads through input(); it never sources owner fields from flags/JSON. The
    seam returns the raw line (gate.py owns .strip()/validation, like ScriptedAsker)."""
    from agentcy import cli
    seen = {}

    def _fake_input(prompt=""):
        seen["prompt"] = prompt
        return "core"

    monkeypatch.setattr("builtins.input", _fake_input)
    ao = cli._ask_owner_from_input()
    assert ao("circle_fit?", ("core", "edge", "outside")) == "core"
    assert "core/edge/outside" in seen["prompt"]  # options surfaced to the owner


# --- P8.5 watchlist add/list (R6: gate.watchlist_add, C.1 cap surfaced) ----------

def test_watchlist_add_prompts_then_calls_gate(tmp_db, fixed_clock, monkeypatch):
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    answers = iter(["compounder I understand", "reading"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    got = {}
    fake = types.SimpleNamespace(
        watchlist_add=lambda conn, *, ticker, one_line_why, idea_source, clock:
            got.update(ticker=ticker, why=one_line_why, src=idea_source) or 5)
    monkeypatch.setattr(cli, "_gate", lambda: fake)
    assert cli.main(["watchlist", "add", "NET"]) == 0
    assert got == {"ticker": "NET", "why": "compounder I understand", "src": "reading"}


def test_watchlist_add_cap10_exits_1(tmp_db, fixed_clock, monkeypatch, capsys):
    """C.1 cap: P4's watchlist_add raises WatchlistFull; the handler surfaces it as
    exit 1 with a clean message, never a stack trace."""
    from agentcy import gate
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    monkeypatch.setattr("builtins.input",
                        lambda prompt="": "own_research" if "source" in prompt else "why")

    def boom(conn, **k):
        raise gate.WatchlistFull("watchlist is full (10 raw items). ... (C.1)")

    monkeypatch.setattr(cli, "_gate", lambda: types.SimpleNamespace(
        WatchlistFull=gate.WatchlistFull, watchlist_add=boom))
    assert cli.main(["watchlist", "add", "X"]) == 1
    assert "watchlist is full" in capsys.readouterr().err


def test_watchlist_list_json(tmp_db, fixed_clock, monkeypatch, capsys):
    import json
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    monkeypatch.setattr("agentcy.db.fetch_watchlist",
                        lambda conn, **k: [{"ticker": "NET", "stage": "raw", "one_line_why": "w"}])
    assert cli.main(["watchlist", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["ticker"] == "NET"


def test_watchlist_list_plain(tmp_db, fixed_clock, monkeypatch, capsys):
    cli = _wire(monkeypatch, tmp_db, fixed_clock)
    monkeypatch.setattr("agentcy.db.fetch_watchlist",
                        lambda conn, **k: [{"ticker": "NET", "stage": "raw", "one_line_why": "w"}])
    assert cli.main(["watchlist", "list"]) == 0
    out = capsys.readouterr().out
    assert "NET" in out and "raw" in out
