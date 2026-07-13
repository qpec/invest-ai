"""Task 9 — weekly-auto eToro refresh with fail-loud fallback (D.2).

Network-free by construction: `weekly._etoro_client` is monkeypatched to a FakeClient
and `weekly.etoro.fetch_etoro_snapshot` is stubbed, so no yfinance/eToro/DB-price
network call ever happens. The guard means the whole thing is a no-op without env keys,
and any eToro/FX failure MUST NOT crash the weekly run — it enqueues a notice and the
run proceeds on the last good snapshot.
"""
from datetime import datetime, timezone

from agentcy import db, mirror, runlog
from agentcy.clock import FixedClock

SAT = FixedClock(datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc))


def _weekly_run_id(conn):
    """A real run_log parent so a run_id FK inserts cleanly (mirrors the sweep handle)."""
    return runlog.start(conn, "weekly", "2026-07-11", clock=SAT).run_id


class _FakeClient:
    def get_portfolio(self):
        return {"clientPortfolio": {"credit": 100.0, "positions": [
            {"instrumentID": 4148, "units": 2.0, "amount": 400.0, "openRate": 200.0,
             "openDateTime": "2024-06-01T00:00:00.000Z", "isBuy": True, "leverage": 1.0},
        ]}}

    def get_instruments(self, ids):
        return [{"instrumentID": 4148, "symbolFull": "AAPL", "instrumentTypeID": 5}]


def _set_keys(monkeypatch):
    monkeypatch.setenv("AGENTCY_ETORO_API_KEY", "dummy-api")
    monkeypatch.setenv("AGENTCY_ETORO_USER_KEY", "dummy-user")


def _clear_keys(monkeypatch):
    monkeypatch.delenv("AGENTCY_ETORO_API_KEY", raising=False)
    monkeypatch.delenv("AGENTCY_ETORO_USER_KEY", raising=False)


def _stub_client_and_identity_fx(monkeypatch):
    """Client seam -> FakeClient; production_fx -> identity so no yfinance/DB fetch runs."""
    from agentcy.jobs import weekly
    monkeypatch.setattr(weekly, "_etoro_client", lambda api_key, user_key: _FakeClient())
    monkeypatch.setattr(weekly.etoro, "production_fx",
                        lambda conn, **kw: (lambda amount, ccy: amount))


def test_happy_path_writes_api_pull_snapshot(tmp_db, monkeypatch):
    from agentcy.jobs import weekly
    conn = tmp_db
    _set_keys(monkeypatch)
    _stub_client_and_identity_fx(monkeypatch)
    # real fetch_etoro_snapshot runs against the FakeClient + identity fx
    weekly.etoro_refresh(conn, run_id=_weekly_run_id(conn), clock=SAT, state_dir=None)
    snap = db.fetch_latest_snapshot(conn)
    assert snap is not None
    assert snap["source"] == "api_pull"


def test_failure_path_no_snapshot_and_notice_enqueued(tmp_db, monkeypatch):
    from agentcy.fetch import etoro
    from agentcy.jobs import weekly
    conn = tmp_db
    _set_keys(monkeypatch)
    _stub_client_and_identity_fx(monkeypatch)
    monkeypatch.setattr(
        weekly.etoro, "fetch_etoro_snapshot",
        lambda *a, **k: (_ for _ in ()).throw(etoro.EtoroError("api down")))

    # must not raise
    weekly.etoro_refresh(conn, run_id=_weekly_run_id(conn), clock=SAT, state_dir=None)

    # no snapshot written
    assert db.fetch_latest_snapshot(conn) is None
    # a failure notice was enqueued
    row = db.fetch_outbox_by_key(conn, f"etoro-fail:{SAT.now().date().isoformat()}")
    assert row is not None
    assert row["kind"] == "notice"
    assert "eToro fetch failed" in row["payload_html"]
    assert "holdings unchanged" in row["payload_html"]


def test_failure_path_reports_last_snapshot_as_of(seeded_portfolio, monkeypatch):
    from agentcy.fetch import etoro
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    _set_keys(monkeypatch)
    _stub_client_and_identity_fx(monkeypatch)
    monkeypatch.setattr(
        weekly.etoro, "fetch_etoro_snapshot",
        lambda *a, **k: (_ for _ in ()).throw(etoro.EtoroError("api down")))

    prev = db.fetch_latest_snapshot(conn)
    weekly.etoro_refresh(conn, run_id=_weekly_run_id(conn), clock=SAT, state_dir=None)
    # last good snapshot is untouched (still the manual_export baseline)
    assert db.fetch_latest_snapshot(conn)["snapshot_id"] == prev["snapshot_id"]
    row = db.fetch_outbox_by_key(conn, f"etoro-fail:{SAT.now().date().isoformat()}")
    assert row is not None
    assert prev["as_of"] in row["payload_html"]


def test_disabled_path_is_a_no_op(tmp_db, monkeypatch):
    from agentcy.jobs import weekly
    conn = tmp_db
    _clear_keys(monkeypatch)
    # if either seam is reached, blow up — the guard must return first
    monkeypatch.setattr(weekly, "_etoro_client",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("client built")))
    monkeypatch.setattr(weekly.etoro, "fetch_etoro_snapshot",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetch called")))

    weekly.etoro_refresh(conn, run_id=1, clock=SAT, state_dir=None)

    assert db.fetch_latest_snapshot(conn) is None
    # no notice enqueued either
    assert db.fetch_outbox_queued(conn) == []


def test_second_same_date_failure_after_sent_does_not_raise(tmp_db, monkeypatch):
    """Crashed-run re-sweep guarantee: a SECOND same-date eToro failure must NOT raise
    even after the first failure notice was already marked 'sent'/'collapsed'. A raw
    per-date dedupe_key would make outbox.enqueue raise ValueError on the already-sent
    key, escaping etoro_refresh -> crashing the weekly run. qualified_key promotes the
    key to an attempt-qualified revision so the re-enqueue never raises."""
    from agentcy.fetch import etoro
    from agentcy.jobs import weekly
    conn = tmp_db
    _set_keys(monkeypatch)
    _stub_client_and_identity_fx(monkeypatch)
    monkeypatch.setattr(
        weekly.etoro, "fetch_etoro_snapshot",
        lambda *a, **k: (_ for _ in ()).throw(etoro.EtoroError("api down")))

    # First failing call enqueues the notice under the raw base key.
    weekly.etoro_refresh(conn, run_id=_weekly_run_id(conn), clock=SAT, state_dir=None)
    base = f"etoro-fail:{SAT.now().date().isoformat()}"
    row = db.fetch_outbox_by_key(conn, base)
    assert row is not None
    # Mark the notice 'sent' (the daemon delivered it) — the state a re-sweep hits.
    db.update_outbox_state(conn, row["outbox_id"], status="sent")

    # Second same-date failing call must NOT raise (weekly path stays alive).
    weekly.etoro_refresh(conn, run_id=_weekly_run_id(conn), clock=SAT, state_dir=None)

    # A fresh attempt-qualified revision row exists and is queued.
    rev = db.fetch_outbox_by_key(conn, f"{base}#a2")
    assert rev is not None
    assert rev["status"] == "queued"
    assert rev["kind"] == "notice"


def test_run_one_invokes_etoro_refresh_first(seeded_portfolio, tmp_path, monkeypatch):
    """run_one must call etoro_refresh before refresh_batch (D.2 D.2 top-of-loop)."""
    from agentcy.jobs import weekly
    conn = seeded_portfolio["conn"]
    order = []
    monkeypatch.setattr(weekly, "etoro_refresh",
                        lambda conn, *, run_id, clock, state_dir: order.append("etoro"))
    monkeypatch.setattr(weekly, "refresh_batch",
                        lambda conn, *, run_id, clock, state_dir: (order.append("batch"),
                                                                   {"data_health": [], "spooled": []})[1])

    class _Handle:
        run_id = _weekly_run_id(conn)
        scheduled_for = "2026-07-11"

    weekly.run_one(conn, _Handle(), clock=SAT, state_dir=tmp_path)
    assert order[:2] == ["etoro", "batch"]
