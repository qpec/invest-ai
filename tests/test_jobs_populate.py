"""The populate job (populator design 4/6/7). Fake fetch layer + advancing clock; no sleep,
no network. Time-box and rate-limit early-stop are deterministic.

Run_type is 'populate' (review fix M3: migration 002 added a dedicated 'populate' value to the
run_log CHECK, so the job logs under its own run_type — this overrides the task-text 'scout')."""
import bz2
import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from agentcy import config, db, populate
from agentcy.clock import Clock, FixedClock
from agentcy.jobs import populate as job

START = datetime(2026, 7, 8, 1, 30, tzinfo=timezone.utc)
AMS = ZoneInfo("Europe/Amsterdam")  # scheduled_for is the Amsterdam-night date (plan note 8)

CSV = (
    "symbol,name,sector,industry,country,market_cap\n"
    "MSFT,Microsoft,Information Technology,Software,United States,mega_cap\n"
    "VEEV,Veeva,Information Technology,Software,United States,large_cap\n"
    "SAP,SAP,Information Technology,Software,Germany,large_cap\n"
)


class AdvancingClock(Clock):
    """Each now() advances by `step` — a wall-clock time-box exercised with no real sleep."""
    def __init__(self, start, step_seconds):
        self._t = start
        self._step = timedelta(seconds=step_seconds)

    def now(self):
        t = self._t
        self._t = self._t + self._step
        return t


class _FakeYf:
    def __init__(self, *, rate_limit_from=None):
        self.calls = []
        self._rl_from = rate_limit_from

    def _maybe_rl(self, t):
        from agentcy.fetch.yf import RateLimited
        if self._rl_from is not None and t in self._rl_from:
            raise RateLimited("throttled")

    def fetch_statements(self, t, *, state_dir):
        self.calls.append(t)
        self._maybe_rl(t)
        return _pack()

    def fetch_shares_full(self, t, *, state_dir):
        return pd.Series([7.4e9], index=pd.to_datetime(["2026-07-01"]))

    def fetch_daily_bars(self, t, *, state_dir):
        return pd.DataFrame(
            {"close": [500.0], "adj_close": [500.0], "dividend": [0.0], "currency": ["USD"]},
            index=pd.to_datetime(["2026-07-07"]))


def _pack():
    cols = pd.to_datetime(["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])
    inc = pd.DataFrame({c: {"Total Revenue": 1e11, "EBITDA": 4e10, "EBIT": 3.5e10,
                            "Gross Profit": 7e10, "Net Income": 3e10} for c in cols})
    bal = pd.DataFrame({c: {"Total Debt": 5e10, "Cash And Cash Equivalents": 8e10,
                            "Total Assets": 4e11, "Current Assets": 3e11,
                            "Working Capital": 2e10} for c in cols})
    cf = pd.DataFrame({c: {"Operating Cash Flow": 4e10, "Capital Expenditure": -5e9,
                           "Stock Based Compensation": 2e9} for c in cols})
    return {"income": inc, "balance": bal, "cashflow": cf}


class _KeepOpen:
    """Delegates every attribute to the shared tmp_db connection but makes close() a no-op,
    so the job's own ``finally: conn.close()`` does not invalidate the handle the test inspects
    afterwards. sqlite3.Connection.close is read-only, so we wrap rather than patch it."""
    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _inject_db(monkeypatch, conn):
    """Point the job's _open_db seam at the shared tmp_db (close() neutralised). Production
    main() still owns and closes the real connection it opens; only the test handle survives."""
    monkeypatch.setattr(job, "_open_db", lambda state_dir: _KeepOpen(conn))


def _seed_universe(tmp_path, conn):
    path = tmp_path / "universe" / "equities.bz2"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bz2.compress(CSV.encode()))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    config.set(conn, "universe_pin_sha", sha, reason="t", actor="owner",
               clock=FixedClock(START))
    # Task 9's seeded defaults have not landed yet; the job reads these three config keys
    # unconditionally, so seed them here to keep the suite green (plan §5e option b).
    for k, v in [("populate_starter_size", "500"),
                 ("populate_nightly_minutes", "90"),
                 ("populate_dead_after_failures", "3"),
                 ("populate_enabled", "true")]:
        config.set(conn, k, v, reason="t", actor="owner", clock=FixedClock(START))
    return path


def test_populate_fetches_targets_within_budget(tmp_db, tmp_path, monkeypatch):
    _seed_universe(tmp_path, tmp_db)
    fake = _FakeYf()
    monkeypatch.setattr(populate, "yf", fake)
    _inject_db(monkeypatch, tmp_db)
    rc = job.main(clock=AdvancingClock(START, step_seconds=1), state_dir=tmp_path,
                  budget=2, minutes=None)
    assert rc == 0
    # two highest-liquidity names fetched (MSFT mega, then a large_cap), SAP left for later
    latest = db.fetch_universe_fetch_latest(tmp_db)
    assert latest["MSFT"]["outcome"] == "ok"
    assert len(latest) == 2


def test_populate_time_box_stops_the_loop(tmp_db, tmp_path, monkeypatch):
    _seed_universe(tmp_path, tmp_db)
    monkeypatch.setattr(populate, "yf", _FakeYf())
    _inject_db(monkeypatch, tmp_db)
    # step 60s/now-call, minutes=1: the box is exhausted after ~1 name.
    rc = job.main(clock=AdvancingClock(START, step_seconds=60), state_dir=tmp_path,
                  budget=None, minutes=1)
    assert rc == 0
    assert len(db.fetch_universe_fetch_latest(tmp_db)) <= 1


def test_populate_rate_limit_stops_early_and_reports_degraded(tmp_db, tmp_path, monkeypatch):
    _seed_universe(tmp_path, tmp_db)
    monkeypatch.setattr(populate, "yf", _FakeYf(rate_limit_from={"MSFT"}))
    _inject_db(monkeypatch, tmp_db)
    rc = job.main(clock=AdvancingClock(START, step_seconds=1), state_dir=tmp_path,
                  budget=10, minutes=None)
    assert rc == 1  # DEGRADED -> nonzero exit
    latest = db.fetch_universe_fetch_latest(tmp_db)
    assert latest["MSFT"]["outcome"] == "rate_limited"
    run = db.fetch_run(tmp_db, "populate", START.astimezone(AMS).date().isoformat())
    assert run is not None and run["status"] == "degraded"


def test_populate_same_day_rerun_after_success_is_clean_noop(tmp_db, tmp_path, monkeypatch):
    """A same-Amsterdam-day manual re-run AFTER a successful night is the advertised
    resumable behaviour: it must exit 0 cleanly, never raise. The first run finishes
    'ok'; the second run under the same scheduled_for key short-circuits on the already-
    done run_log row (mirroring runner.sweep_and_run's is_done guard)."""
    _seed_universe(tmp_path, tmp_db)
    monkeypatch.setattr(populate, "yf", _FakeYf())
    _inject_db(monkeypatch, tmp_db)
    key = START.astimezone(AMS).date().isoformat()

    rc1 = job.main(clock=AdvancingClock(START, step_seconds=1), state_dir=tmp_path,
                   budget=2, minutes=None)
    assert rc1 == 0
    run1 = db.fetch_run(tmp_db, "populate", key)
    assert run1 is not None and run1["status"] == "ok"

    # Second same-day run: another AdvancingClock anchored the same Amsterdam night. The
    # prior key finished 'ok', so runlog.start would raise RuntimeError without the guard.
    rc2 = job.main(clock=AdvancingClock(START, step_seconds=1), state_dir=tmp_path,
                   budget=2, minutes=None)
    assert rc2 == 0  # clean resumable no-op, not a traceback
    # The finished 'ok' run is untouched (no new attempt stamped by the short-circuit).
    run2 = db.fetch_run(tmp_db, "populate", key)
    assert run2 is not None and run2["status"] == "ok"
    assert run2["attempt"] == run1["attempt"]
