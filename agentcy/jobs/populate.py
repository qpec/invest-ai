"""The fundamentals-archive populate job (design 2026-07-10 section 4/6/7).

Paced background walk of the universe in liquidity order, filling the append-only archive
so `agentcy scout run grade` grades from cache. Time-boxed by populate_nightly_minutes (or
--budget). Logs one run_log row (run_type 'populate', review fix M3) and one universe_fetch
row per attempt. Sustained rate-limiting stops the night early and returns DEGRADED (NFR6).

No LLM, no new dependency, no new fetch door: every Yahoo call goes through populate.fetch_one
-> fetch/yf.py, which paces box-wide (>=2s + jitter). The loop owns budget/time-box; fetch_one
owns nothing but one fetch per source.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from agentcy import config as config_mod, db, populate, runlog
from agentcy.clock import Clock, SystemClock
from agentcy.render import populate as render_populate  # milestone note (Task 6)
from agentcy.scout import load_universe

RUN_TYPE = "populate"  # review fix M3: migration 002 added 'populate' to the run_log CHECK
AMS = ZoneInfo("Europe/Amsterdam")


def _open_db(state_dir: Path):
    """Seam: tests monkeypatch this to inject the tmp_db connection."""
    return db.open_db(state_dir)


def main(*, clock: Clock | None = None, state_dir: Path | None = None,
         budget: int | None = None, minutes: int | None = None) -> int:
    """Systemd/CLI entry (design 7). Returns 0 ok, 1 degraded (sustained rate-limit)."""
    clock = clock or SystemClock()
    state_dir = state_dir or db.state_dir()
    conn = _open_db(state_dir)
    try:
        return _run(conn, clock=clock, state_dir=state_dir, budget=budget, minutes=minutes)
    finally:
        conn.close()


def _run(conn, *, clock, state_dir, budget, minutes) -> int:
    start = clock.now()
    # One populate run per Amsterdam night (plan note 8). A same-day manual re-run resumes:
    # if the night finished OK/degraded, the key is already done, so short-circuit clean
    # (exit 0) mirroring runner.sweep_and_run's is_done guard; a failed/interrupted key is
    # re-claimed by runlog.start and re-run. Without this guard a re-run after a SUCCESSFUL
    # night would hit runlog.start's "already finished" RuntimeError.
    scheduled_for = start.astimezone(AMS).date().isoformat()
    if runlog.is_done(conn, RUN_TYPE, scheduled_for):
        return 0
    handle = runlog.start(conn, RUN_TYPE, scheduled_for, clock=clock)

    if minutes is None and budget is None:
        minutes = config_mod.get_int(conn, "populate_nightly_minutes")
    starter_size = config_mod.get_int(conn, "populate_starter_size")
    dead_after = config_mod.get_int(conn, "populate_dead_after_failures")

    pin = config_mod.get(conn, "universe_pin_sha")
    universe = load_universe(Path(state_dir) / "universe" / "equities.bz2", expect_sha=pin)
    universe = populate.filter_us_eu(universe)          # design 2: US+EU only, not global
    ranked = populate.rank_universe(universe)

    # A generous budget cap so the time-box is the real limiter when minutes is set.
    work_budget = budget if budget is not None else len(ranked)
    targets = populate.next_targets(conn, ranked, budget=work_budget, as_of=start,
                                    dead_after_failures=dead_after)

    deadline = None if minutes is None else start + timedelta(minutes=minutes)
    counts = {o: 0 for o in populate.Outcome}
    degraded = False
    for t in targets:
        now = clock.now()
        if deadline is not None and now >= deadline:
            break  # wall-clock time-box (design 4)
        fetched_at = db.to_iso(now)
        outcome = populate.fetch_one(conn, t, run_id=handle.run_id,
                                     fetched_at=fetched_at, state_dir=state_dir)
        db.append_universe_fetch(conn, yf_ticker=t, outcome=outcome.value,
                                 attempted_at=fetched_at, run_id=handle.run_id)
        conn.commit()
        counts[outcome] += 1
        if outcome is populate.Outcome.RATE_LIMITED:
            degraded = True
            break  # stop the night; resume tomorrow (design 6)

    render_populate.maybe_emit_milestones(conn, ranked, starter_size=starter_size,
                                          run_id=handle.run_id, as_of=start, clock=clock)
    conn.commit()

    status = "degraded" if degraded else "ok"
    outputs = {"targets": len(targets), "counts": {o.value: counts[o] for o in counts}}
    runlog.finish(conn, handle.run_id, status=status, outputs=outputs, clock=clock)
    return 1 if degraded else 0
