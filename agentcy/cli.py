"""agentcy desk CLI — tech-arch §10. FR9 fields (conviction, mgmt_trust, circle_fit,
ten_year_statement) are interactive-prompt-ONLY: no flag, no stdin-JSON, no import path.
--json exists on OUTPUT surfaces only (thesis show / ask list / watchlist list).
Job exceptions propagate uncaught: the degraded letter is already in the outbox
(P6, §1.3) and the nonzero exit is what fires OnFailure=."""
from __future__ import annotations

import argparse
import sys
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


def _archive_dir():
    """§8: the archive lives at <state_dir>/archive — derived, never hardcoded."""
    from agentcy import db
    return db.state_dir() / "archive"


_HANDLERS: dict = {}  # filled by the tasks below: name -> callable(args) -> int
_HANDLERS["run"] = _cmd_run
_HANDLERS["bot"] = _cmd_bot
_HANDLERS["render"] = _cmd_render
_HANDLERS["scout"] = _cmd_scout


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = _HANDLERS.get(args.handler)
    if handler is None:
        print(f"agentcy: '{args.handler}' is not wired yet", file=sys.stderr)
        return 2
    return int(handler(args) or 0)
