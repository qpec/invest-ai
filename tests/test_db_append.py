"""Append helpers: contracts §3.1 write path."""
from __future__ import annotations

import pytest

from agentcy import db

T = "2026-07-08T05:00:00Z"

THESIS_V1 = {
    "thesis_id": "TH-MSFT-001", "version": 1, "business_model_2s": "Sells clouds. Rents seats.",
    "moat_types_json": '["switching_costs"]', "moat_evidence": "renewal rates",
    "owner_earnings_json": "{}", "owner_earnings_narrative": "solid",
    "value_at_purchase": 28.0, "fair_band_low": 20.0, "fair_band_high": 30.0,
    "conviction": "high", "mgmt_trust": "trusted_professional", "circle_fit": "core",
    "time_horizon": "10y_plus", "ten_year_statement": "still selling clouds",
    "status_buy_flag": 0, "actor": "owner", "journal_ref": 1, "created_at": T,
}


def _run(conn) -> int:
    return conn.execute(
        "INSERT INTO run_log (run_type, scheduled_for, created_at, started_at)"
        " VALUES ('weekly', '2026-07-04', ?, ?)", (T, T)).lastrowid


def test_append_snapshot_and_positions(tmp_db):
    sid = db.append_snapshot(tmp_db, as_of=T, source="manual_export",
                             cash_balance_eur=1000.0, created_at=T)
    assert isinstance(sid, int) and sid >= 1
    db.append_positions(tmp_db, sid, [
        {"symbol": "MSFT", "yf_ticker": "MSFT", "instrument_type": "stock",
         "quantity": 10, "avg_open_price": 300.0, "native_currency": "USD",
         "mv_native": 4000.0, "mv_eur": 3600.0, "weight": 0.36},
        {"symbol": "BTC", "instrument_type": "crypto", "quantity": 0.1,
         "native_currency": "USD", "mv_native": 6000.0, "mv_eur": 5400.0,
         "weight": 0.54},
    ])
    rows = tmp_db.execute(
        "SELECT * FROM position WHERE snapshot_id=? ORDER BY symbol", (sid,)).fetchall()
    assert len(rows) == 2
    assert rows[0]["symbol"] == "BTC" and rows[0]["yf_ticker"] is None   # MA-4 non-mappable
    assert rows[0]["leverage"] == 1.0 and rows[0]["avg_open_price"] is None
    assert rows[1]["avg_open_price"] == 300.0                            # record-keeping column


def test_append_fundamentals_dedup_on_fingerprint(tmp_db):
    kw = dict(yf_ticker="MSFT", statement_type="income", period_end="2026-03-31",
              payload_json="{}", fingerprint="fp1", fetched_at=T, run_id=None)
    assert db.append_fundamentals_period(tmp_db, **kw) is True
    assert db.append_fundamentals_period(tmp_db, **kw) is False          # seen: no new row
    assert db.append_fundamentals_period(tmp_db, **{**kw, "fingerprint": "fp2"}) is True
    n = tmp_db.execute("SELECT COUNT(*) FROM fundamentals_period").fetchone()[0]
    assert n == 2


def test_append_thesis_version_and_generated_mid(tmp_db):
    db.append_thesis(tmp_db, thesis_id="TH-MSFT-001", ticker="MSFT",
                     origin="gate", created_at=T)
    db.append_thesis_version(tmp_db, THESIS_V1)
    row = tmp_db.execute("SELECT fair_band_mid FROM thesis_version").fetchone()
    assert row["fair_band_mid"] == 25.0                                  # MA-9 generated column
    log_id = db.append_thesis_status(tmp_db, thesis_id="TH-MSFT-001",
                                     status="draft", changed_at=T, cause="gate verdict")
    assert log_id >= 1


def test_append_trigger_and_check_hide_keyword_quoting(tmp_db):
    db.append_thesis(tmp_db, thesis_id="TH-MSFT-001", ticker="MSFT",
                     origin="gate", created_at=T)
    rid = _run(tmp_db)
    tid = db.append_trigger(tmp_db, {
        "thesis_id": "TH-MSFT-001", "introduced_version": 1, "type": "growth_floor",
        "statement": "Revenue growth stays above 10%", "metric": "rev_growth_ttm",
        "comparator": "<", "threshold": 10.0, "moat_link": "switching_costs",
        "persistence": "ttm", "check_method": "automated",
        "data_source": "yf_quarterly_statements", "cadence": "weekly"})
    cid = db.append_trigger_check(tmp_db, {
        "trigger_id": tid, "run_id": rid, "checked_at": T, "result": "PASS",
        "observed_value": 14.2, "headroom": 4.2})
    assert tid >= 1 and cid >= 1


def test_append_journal_entry_and_grade(tmp_db):
    eid = db.append_journal_entry(tmp_db, {
        "ts": T, "decision_type": "buy", "ticker": "MSFT",
        "reasoning_at_the_moment": "thesis holds", "actor": "owner"})
    assert eid > 5                                     # five bootstrap entries seeded
    db.append_journal_grade(tmp_db, entry_id=eid, graded_at=T, outcome_grade="too_early")
    n = tmp_db.execute("SELECT COUNT(*) FROM journal_grade WHERE entry_id=?",
                       (eid,)).fetchone()[0]
    assert n == 1


def test_mapping_helpers_reject_unknown_columns(tmp_db):
    with pytest.raises(ValueError, match="unknown"):
        db.append_event(tmp_db, {"yf_ticker": "MSFT", "source": "owner",
                                 "kind": "earnings", "detected_at": T, "nope": 1})


def test_simple_appends_round_trip(tmp_db):
    sid = db.append_snapshot(tmp_db, as_of=T, source="api_pull",
                             cash_balance_eur=1.0, created_at=T)
    assert db.append_external_flow(tmp_db, snapshot_id=sid, date="2026-07-08",
                                   amount_eur=100.0, direction="deposit") >= 1
    db.append_symbol_map(tmp_db, symbol="NESN", yf_ticker="NESN.SW",
                         valid_from=T, journal_ref=1)
    db.append_designation(tmp_db, symbol="NESN", framework_status="backfill_pending",
                          valid_from=T, journal_ref=1)
    assert db.append_price_rows(tmp_db, [
        {"yf_ticker": "MSFT", "bar_date": "2026-07-07", "close": 500.0,
         "adj_close": 500.0, "currency": "USD", "fetched_at": T},
    ]) == 1
    assert db.append_shares_rows(tmp_db, [
        {"yf_ticker": "MSFT", "obs_date": "2026-07-01", "shares": 7.4e9,
         "fetched_at": T}]) == 1
    db.append_officer_snapshot(tmp_db, yf_ticker="MSFT", officers_json="[]",
                               fingerprint="fp", fetched_at=T)
    db.append_earnings_calendar(tmp_db, yf_ticker="MSFT", expected_date="2026-07-29",
                                fetched_at=T, run_id=None)
    assert db.append_absence_event(tmp_db, kind="on", at=T, journal_ref=1) >= 1
    assert db.append_study_note(tmp_db, ts=T, kind="circle_note", text="x") >= 1
    assert db.append_event(tmp_db, {"yf_ticker": "MSFT", "source": "fingerprint",
                                    "kind": "earnings", "detected_at": T}) >= 1
    db.append_config(tmp_db, key="alert_decision_days", value="9",
                     valid_from="2026-08-01T00:00:00Z", journal_ref=1)
    rid = tmp_db.execute(
        "INSERT INTO run_log (run_type, scheduled_for, created_at, started_at)"
        " VALUES ('daily', '2026-07-08', ?, ?)", (T, T)).lastrowid
    assert db.append_report(tmp_db, {
        "run_id": rid, "type": "daily", "generated_at": T, "period": "2026-07-08",
        "freshness_json": "{}", "content_md": "x",
        "archive_path": "letters/2026-07-08.md", "git_sha": None}) >= 1
