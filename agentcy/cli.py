"""agentcy desk CLI — tech-arch §10. FR9 fields (conviction, mgmt_trust, circle_fit,
ten_year_statement) are interactive-prompt-ONLY: no flag, no stdin-JSON, no import path.
--json exists on OUTPUT surfaces only (thesis show / ask list / watchlist list).
Job exceptions propagate uncaught: the degraded letter is already in the outbox
(P6, §1.3) and the nonzero exit is what fires OnFailure=."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


def _clock():
    """Seam: tests monkeypatch this to inject FixedClock."""
    from agentcy.clock import SystemClock
    return SystemClock()


def _open():
    """Open agentcy.db and apply pending migrations (forward-only at open, §12.6)."""
    from agentcy import db
    conn = db.open_db()
    db.migrate(conn)
    return conn


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentcy", description="stock-agentcy desk CLI (tech-arch §10)")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="scheduled jobs (systemd ExecStart surface)")
    run.add_argument("job", choices=["daily", "weekly", "quarterly", "event"])
    run.set_defaults(handler="run")

    sub.add_parser("bot", help="Telegram long-poll daemon (agentcy-bot.service)").set_defaults(handler="bot")

    gate = sub.add_parser("gate", help="The Gate, C.2-C.6")
    gsub = gate.add_subparsers(dest="gate_cmd", required=True)
    gstart = gsub.add_parser("start")
    gstart.add_argument("ticker")
    gstart.add_argument("--backfill", action="store_true",
                        help="backfill mode: same Gate minus price verdict (C.6)")
    gstart.set_defaults(handler="gate")
    gsub.add_parser("resume").set_defaults(handler="gate")

    scout = sub.add_parser("scout", help="The Scout (H) — human-run only")
    ssub = scout.add_subparsers(dest="scout_cmd", required=True)
    srun = ssub.add_parser("run")
    srun.add_argument("recipe", choices=["qv"])
    srun.set_defaults(handler="scout")

    wl = sub.add_parser("watchlist", help="C.1 watchlist")
    wsub = wl.add_subparsers(dest="wl_cmd", required=True)
    wadd = wsub.add_parser("add")
    wadd.add_argument("ticker")
    wadd.set_defaults(handler="watchlist")
    wlist = wsub.add_parser("list")
    wlist.add_argument("--json", action="store_true")
    wlist.set_defaults(handler="watchlist")

    snap = sub.add_parser("snapshot", help="E.1 snapshot ingestion")
    snsub = snap.add_subparsers(dest="snap_cmd", required=True)
    simp = snsub.add_parser("import")
    simp.add_argument("csv", help="path to the broker CSV export")
    simp.set_defaults(handler="snapshot")
    snsub.add_parser("enter").set_defaults(handler="snapshot")

    jr = sub.add_parser("journal", help="Decision Journal")
    jsub = jr.add_subparsers(dest="journal_cmd", required=True)
    jsub.add_parser("grade").set_defaults(handler="journal")

    th = sub.add_parser("thesis", help="Thesis Register")
    tsub = th.add_subparsers(dest="thesis_cmd", required=True)
    tshow = tsub.add_parser("show")
    tshow.add_argument("thesis_id")
    tshow.add_argument("--json", action="store_true")
    tshow.set_defaults(handler="thesis")
    trev = tsub.add_parser("revise")
    trev.add_argument("thesis_id")
    trev.set_defaults(handler="thesis")

    cfg = sub.add_parser("config", help="journaled operational config (§9)")
    csub = cfg.add_subparsers(dest="config_cmd", required=True)
    cset = csub.add_parser("set")
    cset.add_argument("key")
    cset.add_argument("value")
    cset.add_argument("--reason", required=True)
    cset.set_defaults(handler="config")

    ab = sub.add_parser("absence", help="D.6 pause mode")
    absub = ab.add_subparsers(dest="absence_cmd", required=True)
    astart = absub.add_parser("start")
    astart.add_argument("--until", default=None, help="planned end YYYY-MM-DD (omit = until I resume)")
    astart.set_defaults(handler="absence")
    absub.add_parser("end").set_defaults(handler="absence")

    ask = sub.add_parser("ask", help="D.5 desk fallback")
    ksub = ask.add_subparsers(dest="ask_cmd", required=True)
    klist = ksub.add_parser("list")
    klist.add_argument("--json", action="store_true")
    klist.set_defaults(handler="ask")
    kans = ksub.add_parser("answer")
    kans.add_argument("ask_id")
    kans.set_defaults(handler="ask")

    ev = sub.add_parser("event", help="owner-injected event check (FR6)")
    ev.add_argument("ticker")
    ev.add_argument("--kind", choices=["earnings", "filing", "mgmt", "other"], default="other")
    ev.add_argument("--note", default=None)
    ev.set_defaults(handler="event")

    rd = sub.add_parser("render", help="archive maintenance")
    rd.add_argument("--rebuild", action="store_true", required=True,
                    help="regenerate every archive file from the DB (§8)")
    rd.set_defaults(handler="render")

    return p


def _job_module(name: str):
    """Seam for the P6 job entry points (R1); tests inject fakes here."""
    import importlib
    return importlib.import_module(f"agentcy.jobs.{name}")


def _cmd_run(args) -> int:
    """systemd ExecStart surface (§10). Per R1 the job's main() owns the connection,
    the due-run sweep and (for daily) the S2 dead-man ping; the CLI just forwards
    clock/state_dir and returns main()'s int (0 ok, 1 degraded/failed) verbatim.
    Job exceptions propagate uncaught so OnFailure= fires (§1.3)."""
    from agentcy import db
    return _job_module(args.job).main(clock=_clock(), state_dir=db.state_dir())


def _daemon():
    """Seam: the P7 Telegram long-poll daemon (agentcy-bot.service)."""
    from agentcy.tg import daemon
    return daemon


def _archive():
    """Seam: the P5 archive layer (rebuild regenerates every file from the DB, §8)."""
    from agentcy import archive
    return archive


def _scout():
    """Seam: the P4 Scout (H) — human-run screen, never persisted."""
    from agentcy import scout
    return scout


def _gate():
    """Seam: the P4 Gate (C.1-C.6) + watchlist writes; tests inject fakes here."""
    from agentcy import gate
    return gate


def _mirror():
    """Seam: the P3 Portfolio Mirror (E.1 snapshot ingest); tests inject fakes here."""
    from agentcy import mirror
    return mirror


IDEA_SOURCES = ("own_research", "scout_screen", "reading", "referral")


def _ask_owner_from_input():
    """FR9 owner-field seam: return an AskOwner (prompt, options=None) -> str that
    reads through input(). conviction/mgmt_trust/circle_fit/ten_year_statement enter
    ONLY here — never a flag, never stdin-JSON. gate.py owns the re-ask/validation
    loops (_ask_enum/_ask_nonempty), so this seam just surfaces the choices and reads
    one line. Tests monkeypatch builtins.input."""
    def ask(prompt: str, options=None) -> str:
        suffix = f" [{'/'.join(options)}]" if options else ""
        return input(f"{prompt}{suffix} ")
    return ask


def _prompt(label: str, *, choices: tuple[str, ...] | None = None) -> str:
    """Interactive input; re-asks until a listed choice is given when choices is set."""
    while True:
        val = input(f"{label}: ").strip()
        if choices is None or val in choices:
            return val
        print(f"  choose one of: {', '.join(choices)}")


def _cmd_bot(args) -> int:
    """agentcy-bot.service: hand off to the long-poll daemon. run() never returns
    under systemd (§5.2/§5.3); returns None on a clean stop in tests."""
    _daemon().run()
    return 0


def _cmd_render(args) -> int:
    """agentcy render --rebuild: regenerate every archive file from the DB (§8).
    Archive is derived data, so corruption is never data loss."""
    conn = _open()
    n = _archive().rebuild(conn, archive_dir=_archive_dir())
    print(f"rebuilt {n} archive files")
    return 0


def _cmd_scout(args) -> int:
    """agentcy scout run qv (R6): call the real P4 API scout.run_qv and print the
    ScreenResult for human reading. H.2 forbids storing the result — no DB write here."""
    scout = _scout()
    conn = _open()
    result = scout.run_qv(conn, universe_path=None)
    print(f"[{result.recipe}] {len(result.candidates)} candidate(s):")
    for c in result.candidates:
        print(f"  {c.symbol}: EV/EBITDA {c.ev_ebitda:.1f}  ROIC {c.roic:.1f}%  D/E {c.debt_to_equity:.2f}")
    print()
    print(scout.HONEST_EVIDENCE_NOTE)
    return 0


def _cmd_gate(args) -> int:
    """agentcy gate start/resume (R6). start opens a session and drives C.2-C.6 to a
    verdict; resume continues the single active session. FR9 owner fields flow through
    the injected ask_owner (input()-driven) — never a flag."""
    gate = _gate()
    conn = _open()
    clock = _clock()
    ao = _ask_owner_from_input()
    if args.gate_cmd == "start":
        mode = "backfill" if args.backfill else "gate"
        gate.start(conn, ticker=args.ticker, mode=mode, ask_owner=ao, clock=clock)
        return 0
    from agentcy import db
    row = db.fetch_active_gate_session(conn)
    if row is None:
        print("agentcy: no active gate session to resume", file=sys.stderr)
        return 1
    gate.resume(conn, session_id=row["session_id"], ask_owner=ao, clock=clock)
    return 0


def _cmd_watchlist(args) -> int:
    """agentcy watchlist add/list (C.1). add collects one_line_why + idea_source
    interactively (tg-spec §1.8 keeps the watchlist off the bot; §10 puts it at the
    desk) and calls P4's gate.watchlist_add; the cap-10 WatchlistFull surfaces as
    exit 1, never a stack trace. list is a read/--json OUTPUT surface."""
    conn = _open()
    if args.wl_cmd == "list":
        from agentcy import db
        rows = [dict(r) for r in db.fetch_watchlist(conn)]
        if args.json:
            import json
            print(json.dumps(rows))
        else:
            for r in rows:
                print(f"{r['ticker']:8} {r['stage']:22} {r['one_line_why']}")
        return 0
    gate = _gate()
    why = _prompt("one-line why (the thesis-to-be in a sentence)")
    src = _prompt(f"idea source {IDEA_SOURCES}", choices=IDEA_SOURCES)
    try:
        gate.watchlist_add(conn, ticker=args.ticker, one_line_why=why,
                           idea_source=src, clock=_clock())
    except gate.WatchlistFull as exc:
        print(f"agentcy: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_snapshot(args) -> int:
    """agentcy snapshot import <csv> / enter (E.1). Parse via the P3 adapter, ingest,
    then surface the reconciliation deltas. The handler stops at surfacing — it does NOT
    mint R asks (the §3.9 ingest_snapshot contract puts 'caller mints one R ask per Delta'
    on the bot/asks layer); at the desk the deltas point the owner to `ask`/bot follow-up."""
    conn = _open()
    m = _mirror()
    if args.snap_cmd == "import":
        snap = m.parse_etoro_csv(Path(args.csv).read_text(encoding="utf-8"))
    else:  # enter: paste on stdin
        print("Paste positions, then EOF (Ctrl-D):", file=sys.stderr)
        snap = m.parse_manual_text(sys.stdin.read())
    snapshot_id, deltas = m.ingest_snapshot(conn, snap, clock=_clock())
    if not deltas:
        print(f"snapshot {snapshot_id} accepted — everything reconciles.")
        return 0
    print(f"snapshot {snapshot_id} accepted — {len(deltas)} unreconciled delta(s):")
    for d in deltas:
        print(f"  [{d.kind}] {d.symbol or ''} — {d.detail}")
    print("Open loops recorded; answer them via `agentcy ask list` or the bot.")
    return 0


def _cmd_config(args) -> int:
    """agentcy config set <key> <value> --reason (§9): journaled operational config.
    config.set is one transaction (journal-entry-first, then config append) inside the
    config module — the handler never touches the journal directly."""
    from agentcy import config
    conn = _open()
    config.set(conn, args.key, args.value, reason=args.reason, actor="owner", clock=_clock())
    print(f"config {args.key} = {args.value} (journaled)")
    return 0


def _cmd_absence(args) -> int:
    """agentcy absence start [--until]/end (D.6). Pause/resume flow through the shared
    absence writer (R3) so the desk and the bot write the on/off stream identically:
    journal-FK first, then the FK-referencing absence_event row. Windows are derived at
    read by clock.py; nothing here mutates history."""
    from agentcy import absence
    conn = _open()
    clock = _clock()
    if args.absence_cmd == "start":
        planned_end = f"{args.until}T00:00:00Z" if args.until else None
        absence.pause(conn, planned_end=planned_end,
                      reason="Pause on (D.6): counters freeze; alerts still deliver.",
                      clock=clock)
        print("Absence started. Deadlines and skip counters freeze; alerts still deliver.")
    else:
        absence.resume(conn, reason="Pause off (D.6): counters live again.", clock=clock)
        print("Absence ended. Frozen counters are live again.")
    conn.commit()
    return 0


def _register():
    """Seam: the P3 Thesis Register (A.1-A.3); tests inject fakes here."""
    from agentcy import register
    return register


def _journal():
    """Seam: the P3 Decision Journal (F.1); tests inject fakes here."""
    from agentcy import journal
    return journal


def _asks():
    """Seam: the P3 Ask register (D.5 desk fallback); tests inject fakes here."""
    from agentcy import asks
    return asks


def _events():
    """Seam: the P3 event spool (§1.5 owner-sensor channel); tests inject fakes here."""
    from agentcy import events
    return events


# FR9 owner fields carry enumerated choices; other A.1 version fields are free text.
_REVISION_CHOICES = {
    "conviction": ("high", "medium", "low"),
    "mgmt_trust": ("trusted_owner_operator", "trusted_professional", "neutral", "distrust"),
    "circle_fit": ("core", "edge"),
}


def _collect_revision_changes() -> dict:
    """Interactive-ONLY revision collector (FR9): prompt field-by-field for the A.1 fields
    the owner names. FR9 fields (conviction/mgmt_trust/circle_fit/ten_year_statement) enter
    here through input() with enumerated choices where applicable — never a flag, never JSON.
    Goalpost-guard / band re-anchoring is enforced downstream in register.revise (A.3)."""
    from agentcy.register import _VERSION_COLUMNS
    allowed = sorted(_VERSION_COLUMNS)
    picked = _prompt(f"fields to revise (comma-separated from {', '.join(allowed)})")
    changes: dict = {}
    for name in (f.strip() for f in picked.split(",")):
        if name not in _VERSION_COLUMNS:
            continue
        changes[name] = _prompt(f"  {name}", choices=_REVISION_CHOICES.get(name))
    return changes


def _cmd_thesis(args) -> int:
    """agentcy thesis show/revise (A.1-A.3). show is a read/--json OUTPUT surface; revise
    journals the reason first (F.1) then hands the interactively-collected changes to
    register.revise, which enforces the goalpost guard and band re-anchor rules (A.3)."""
    conn = _open()
    reg = _register()
    if args.thesis_cmd == "show":
        row = reg.current(conn, args.thesis_id)
        if args.json:
            import json
            print(json.dumps(dict(row)))
        else:
            for k, v in dict(row).items():
                print(f"{k:24} {v}")
        return 0
    from agentcy.journal import EntryIn
    clock = _clock()
    reason = _prompt("reason for revision")
    changes = _collect_revision_changes()
    je = _journal().append(conn, EntryIn(
        decision_type="thesis_revision", ticker=None, thesis_ref=args.thesis_id,
        reasoning_at_the_moment=reason, actor="owner"), clock=clock)
    new_v = reg.revise(conn, args.thesis_id, changes, reason=reason, actor="owner",
                       journal_ref=je, clock=clock)
    conn.commit()
    print(f"{args.thesis_id} revised to v{new_v}")
    return 0


def _cmd_journal(args) -> int:
    """agentcy journal grade (F.1): walk the due-for-review entries and grade each against
    its pre-committed expectation/falsifier — never raw price. Process is judged separately
    from outcome (the decision journal's whole point)."""
    conn = _open()
    jr = _journal()
    clock = _clock()
    due = jr.due_for_review(conn, as_of=clock.now())
    if not due:
        print("no journal entries are due for review.")
        return 0
    for row in due:
        eid = row["entry_id"]
        print(f"JE-{eid}  {row['decision_type']}  {row['ticker'] or ''}".rstrip())
        grade = _prompt("  outcome_grade", choices=("good", "neutral", "bad", "too_early"))
        note = _prompt("  note (optional)") or None
        jr.grade(conn, eid, outcome_grade=grade, note=note, clock=clock)
        print(f"graded JE-{eid}: {grade}")
    conn.commit()
    return 0


def _cmd_ask(args) -> int:
    """agentcy ask list/answer (D.5 desk fallback). list is a read/--json OUTPUT surface;
    answer collects the choice (validated against the ask's options) or free text and hands
    it to asks.answer, which does the authoritative server-side validation."""
    conn = _open()
    ak = _asks()
    if args.ask_cmd == "list":
        asks_open = ak.open_asks(conn)
        if args.json:
            import json
            print(json.dumps([
                {"ask_id": a.ask_id, "kind": a.kind, "prompt": a.prompt,
                 "options": list(a.options), "expects_freetext": a.expects_freetext}
                for a in asks_open]))
        else:
            for a in asks_open:
                print(f"{a.ask_id} [{a.kind}] {a.prompt}")
        return 0
    ask = ak.get(conn, args.ask_id)
    if ask is None:
        print(f"agentcy: no ask {args.ask_id}", file=sys.stderr)
        return 1
    choice = text = None
    if ask.options:
        choice = _prompt("choice", choices=tuple(ask.options))
    elif ask.expects_freetext:
        text = _prompt("answer")
    outcome = ak.answer(conn, args.ask_id, choice=choice, text=text, clock=_clock())
    conn.commit()
    if outcome.already_recorded:
        print("already recorded")
    print(outcome.consequence)
    return 0


def _cmd_event(args) -> int:
    """agentcy event TICKER (FR6 owner-sensor channel, §1.5): identical to the bot's /event —
    write a source='owner' spool file that the event job picks up. The desk never runs the
    check inline; it queues it for jobs.event."""
    from agentcy import db
    ev = _events()
    req = ev.EventRequest(yf_ticker=args.ticker, source="owner", kind=args.kind,
                          note=args.note, detected_at=db.to_iso(_clock().now()))
    ev.spool_write(db.state_dir(), req)
    print(f"event queued for {args.ticker}; the event job will run it")
    return 0


def _archive_dir():
    """§8: the archive lives at <state_dir>/archive — derived, never hardcoded."""
    from agentcy import db
    return db.state_dir() / "archive"


_HANDLERS: dict = {}  # filled by the tasks below: name -> callable(args) -> int
_HANDLERS["run"] = _cmd_run
_HANDLERS["bot"] = _cmd_bot
_HANDLERS["render"] = _cmd_render
_HANDLERS["scout"] = _cmd_scout
_HANDLERS["gate"] = _cmd_gate
_HANDLERS["watchlist"] = _cmd_watchlist
_HANDLERS["snapshot"] = _cmd_snapshot
_HANDLERS["config"] = _cmd_config
_HANDLERS["absence"] = _cmd_absence
_HANDLERS["thesis"] = _cmd_thesis
_HANDLERS["journal"] = _cmd_journal
_HANDLERS["ask"] = _cmd_ask
_HANDLERS["event"] = _cmd_event


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = _HANDLERS.get(args.handler)
    if handler is None:
        print(f"agentcy: '{args.handler}' is not wired yet", file=sys.stderr)
        return 2
    return int(handler(args) or 0)
