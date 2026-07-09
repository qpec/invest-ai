"""Fetch helpers: latest-wins reads (contracts §3.1, tech-arch §4.4 derivations)."""
from __future__ import annotations

from agentcy import db

T0 = "2026-07-01T00:00:00Z"
T1 = "2026-07-08T05:00:00Z"
T2 = "2026-08-01T00:00:00Z"


def test_fetch_config_current_latest_per_key(tmp_db):
    db.append_config(tmp_db, key="alert_decision_days", value="10",
                     valid_from=T2, journal_ref=1)
    before = db.fetch_config_current(tmp_db, as_of="2026-07-10T00:00:00Z")
    after = db.fetch_config_current(tmp_db, as_of="2026-08-02T00:00:00Z")
    assert before["alert_decision_days"] == "7"        # seeded E.3 default
    assert after["alert_decision_days"] == "10"
    assert before["cash_band_low_pct"] == "5"
    # a key seeded 2026-07-09 (S1) is invisible the day before
    assert "license_exceptions" not in db.fetch_config_current(
        tmp_db, as_of="2026-07-08T12:00:00Z")


def test_fetch_latest_designations_latest_wins(tmp_db):
    db.append_designation(tmp_db, symbol="MSFT", framework_status="backfill_pending",
                          valid_from=T0, journal_ref=1)
    db.append_designation(tmp_db, symbol="MSFT", framework_status="framework",
                          valid_from=T1, journal_ref=1)
    latest = db.fetch_latest_designations(tmp_db)
    assert latest["MSFT"]["framework_status"] == "framework"


def test_fetch_v_price_latest_fetch_per_bar(tmp_db):
    db.append_price_rows(tmp_db, [
        {"yf_ticker": "MSFT", "bar_date": "2026-07-07", "close": 500.0,
         "adj_close": 500.0, "currency": "USD", "fetched_at": T0},
        {"yf_ticker": "MSFT", "bar_date": "2026-07-07", "close": 501.0,
         "adj_close": 501.0, "currency": "USD", "fetched_at": T1},   # re-fetch appends
        {"yf_ticker": "MSFT", "bar_date": "2026-07-06", "close": 495.0,
         "adj_close": 495.0, "currency": "USD", "fetched_at": T0},
    ])
    rows = db.fetch_v_price(tmp_db, "MSFT")
    assert [(r["bar_date"], r["close"]) for r in rows] == [
        ("2026-07-06", 495.0), ("2026-07-07", 501.0)]
    assert [r["bar_date"] for r in db.fetch_v_price(
        tmp_db, "MSFT", start="2026-07-07")] == ["2026-07-07"]


def test_fetch_current_thesis_version_and_status(tmp_db):
    db.append_thesis(tmp_db, thesis_id="TH-MSFT-001", ticker="MSFT",
                     origin="gate", created_at=T0)
    base = {"thesis_id": "TH-MSFT-001", "business_model_2s": "x",
            "moat_types_json": '["brand_trust"]', "moat_evidence": "x",
            "owner_earnings_json": "{}", "owner_earnings_narrative": "x",
            "fair_band_low": 20.0, "fair_band_high": 30.0, "conviction": "high",
            "mgmt_trust": "neutral", "circle_fit": "core", "time_horizon": "10y_plus",
            "ten_year_statement": "x", "actor": "owner", "journal_ref": 1,
            "created_at": T0}
    db.append_thesis_version(tmp_db, {**base, "version": 1})
    db.append_thesis_version(tmp_db, {**base, "version": 2, "created_at": T1})
    assert db.fetch_current_thesis_version(tmp_db, "TH-MSFT-001")["version"] == 2
    db.append_thesis_status(tmp_db, thesis_id="TH-MSFT-001", status="draft",
                            changed_at=T0, cause="gate")
    db.append_thesis_status(tmp_db, thesis_id="TH-MSFT-001", status="intact",
                            changed_at=T1, cause="activated")
    assert db.fetch_current_thesis_status(tmp_db, "TH-MSFT-001")["status"] == "intact"


def test_fetch_armed_triggers_and_latest_check(tmp_db):
    db.append_thesis(tmp_db, thesis_id="TH-MSFT-001", ticker="MSFT",
                     origin="gate", created_at=T0)
    spec = {"thesis_id": "TH-MSFT-001", "introduced_version": 1,
            "type": "growth_floor", "statement": "s", "persistence": "ttm",
            "check_method": "automated", "data_source": "yf_quarterly_statements",
            "cadence": "weekly"}
    t1 = db.append_trigger(tmp_db, spec)
    t2 = db.append_trigger(tmp_db, {**spec, "type": "dilution",
                                    "data_source": "yf_shares_full"})
    db.retire_trigger(tmp_db, t1, retired_at=T1) if hasattr(db, "retire_trigger") else \
        tmp_db.execute('UPDATE "trigger" SET retired_at=? WHERE trigger_id=?', (T1, t1))
    armed = db.fetch_armed_triggers(tmp_db, "TH-MSFT-001")
    assert [r["trigger_id"] for r in armed] == [t2]
    rid = tmp_db.execute(
        "INSERT INTO run_log (run_type, scheduled_for, created_at, started_at)"
        " VALUES ('weekly', '2026-07-04', ?, ?)", (T1, T1)).lastrowid
    db.append_trigger_check(tmp_db, {"trigger_id": t2, "run_id": rid,
                                     "checked_at": T0, "result": "PASS"})
    db.append_trigger_check(tmp_db, {"trigger_id": t2, "run_id": rid,
                                     "checked_at": T1, "result": "FIRE"})
    assert db.fetch_latest_trigger_check(tmp_db, t2)["result"] == "FIRE"


def test_fetch_statement_periods_latest_fingerprint_ascending(tmp_db):
    for pe, fp, ts in (("2026-03-31", "a", T0), ("2026-03-31", "b", T1),
                       ("2025-12-31", "c", T0)):
        db.append_fundamentals_period(tmp_db, yf_ticker="MSFT",
                                      statement_type="income", period_end=pe,
                                      payload_json="{}", fingerprint=fp,
                                      fetched_at=ts, run_id=None)
    rows = db.fetch_statement_periods(tmp_db, "MSFT", "income")
    assert [(r["period_end"], r["fingerprint"]) for r in rows] == [
        ("2025-12-31", "c"), ("2026-03-31", "b")]


def test_fetch_singletons_and_streams(tmp_db):
    assert db.fetch_bot_state(tmp_db)["last_update_id"] == 0
    assert db.fetch_study_state(tmp_db)["mental_model_index"] == 0
    assert db.fetch_latest_snapshot(tmp_db) is None
    db.append_absence_event(tmp_db, kind="on", at=T0, journal_ref=1)
    db.append_absence_event(tmp_db, kind="off", at=T1, journal_ref=1)
    evs = db.fetch_absence_events(tmp_db)
    assert [e["kind"] for e in evs] == ["on", "off"]
    assert db.fetch_run(tmp_db, "daily", "2026-07-08") is None
    assert db.fetch_open_asks(tmp_db) == []
    assert db.fetch_outbox_queued(tmp_db) == []
