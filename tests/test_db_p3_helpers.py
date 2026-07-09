"""tests/test_db_p3_helpers.py — the six helpers P3 adds to db.py."""
from agentcy import db


def test_next_ask_seq_monotonic_per_kind(tmp_db):
    assert db.next_ask_seq(tmp_db, "A") == 1
    db.append_ask(tmp_db, {"ask_id": "A1", "kind": "A", "seq": 1,
                           "created_at": "2026-07-08T05:00:00Z", "prompt": "p",
                           "options_json": "[]", "expects_freetext": 0})
    assert db.next_ask_seq(tmp_db, "A") == 2
    assert db.next_ask_seq(tmp_db, "Q") == 1          # per-kind counter


def test_append_ask_roundtrip(tmp_db):
    db.append_ask(tmp_db, {"ask_id": "Q5", "kind": "Q", "seq": 5,
                           "created_at": "2026-07-08T05:00:00Z", "prompt": "NRR<110%?",
                           "options_json": '["yes","no","cant"]', "expects_freetext": 0,
                           "thesis_ref": "TH-VEEV-001", "trigger_ref": None,
                           "deadline": "2026-07-15T05:00:00Z"})
    row = db.fetch_ask(tmp_db, "Q5")
    assert row["status"] == "open" and row["prompt"] == "NRR<110%?"


def test_append_alert_returns_id(tmp_db):
    _seed_thesis_and_trigger(tmp_db)
    aid = db.append_alert(tmp_db, {"thesis_id": "TH-X-001", "trigger_id": 1, "run_id": 1,
                                   "storm_key": None, "created_at": "2026-07-08T05:00:00Z",
                                   "deadline": "2026-07-15T05:00:00Z"})
    assert aid == 1 and db.fetch_alert(tmp_db, aid)["status"] == "open"


def test_fetch_theses_and_versions_and_asks(tmp_db):
    _seed_thesis_and_trigger(tmp_db)
    assert [t["thesis_id"] for t in db.fetch_theses(tmp_db)] == ["TH-X-001"]
    assert [v["version"] for v in db.fetch_thesis_versions(tmp_db, "TH-X-001")] == [1]
    db.append_ask(tmp_db, {"ask_id": "A9", "kind": "A", "seq": 9,
                           "created_at": "2026-07-08T05:00:00Z", "prompt": "p",
                           "options_json": "[]", "expects_freetext": 0,
                           "thesis_ref": "TH-X-001", "trigger_ref": 1})
    assert [a["ask_id"] for a in db.fetch_asks_for(tmp_db, trigger_ref=1)] == ["A9"]
    assert [a["ask_id"] for a in db.fetch_asks_for(tmp_db, kind="A")] == ["A9"]


def _seed_thesis_and_trigger(conn):
    from agentcy import db as _db
    # run_log(run_id=1) — alert.run_id is a NOT NULL FK; runlog.py owns run_log INSERTs
    # in production, so the seed inserts the parent row directly (plan-test gap; see notes).
    conn.execute(
        "INSERT INTO run_log (run_id, run_type, scheduled_for, created_at, started_at) "
        "VALUES (1, 'weekly', '2026-07-08', '2026-07-08T05:00:00Z', '2026-07-08T05:00:00Z')")
    _db.append_thesis(conn, thesis_id="TH-X-001", ticker="X", origin="gate",
                      created_at="2026-07-08T05:00:00Z")
    _db.append_thesis_version(conn, {
        "thesis_id": "TH-X-001", "version": 1, "business_model_2s": "b.",
        "moat_types_json": '["brand_trust"]', "moat_evidence": "e", "owner_earnings_json": "{}",
        "owner_earnings_narrative": "n", "value_at_purchase": None, "fair_band_low": 20.0,
        "fair_band_high": 30.0, "denominator_note": None, "conviction": "high",
        "mgmt_trust": "neutral", "mgmt_trust_note": None, "circle_fit": "core",
        "circle_fit_note": None, "time_horizon": "10y_plus", "ten_year_statement": "t",
        "status_buy_flag": 0, "status_buy_note": None, "diff_json": None, "reason": None,
        "actor": "owner", "journal_ref": 1, "created_at": "2026-07-08T05:00:00Z"})
    _db.append_trigger(conn, {
        "thesis_id": "TH-X-001", "introduced_version": 1, "type": "growth_floor",
        "statement": "rev YoY < 10%", "metric": "revenue_yoy", "comparator": "<",
        "threshold": 10.0, "moat_link": None, "persistence": "2_consecutive_quarters",
        "check_method": "automated", "data_source": "yf_quarterly_statements",
        "cadence": "weekly", "yes_means": None})
