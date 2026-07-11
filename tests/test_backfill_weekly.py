"""tests/test_backfill_weekly.py - weekly letter reports drafts honestly; Watchdog picks up
an intact backfill thesis with no Watchdog change (only the RF2 draft-status guard)."""
from datetime import datetime, timezone

from agentcy import db

SAT = datetime(2026, 7, 11, 6, 0, tzinfo=timezone.utc)


def test_thesis_less_holding_reported_not_skipped(tmp_db, fixed_clock):
    """A non-cash, non-outside-framework holding with no live thesis is reported as awaiting
    thesis ratification in the weekly re-validation lines, never silently skipped (the old
    `if tid is None: continue` bug)."""
    from agentcy import journal
    from agentcy.jobs import weekly
    from agentcy.journal import EntryIn
    conn = tmp_db
    now = db.to_iso(fixed_clock.now())
    journal.append(conn, EntryIn(decision_type="config_or_designation",
                                 decision_subtype="config_change",
                                 reasoning_at_the_moment="seed", actor="owner"),
                   clock=fixed_clock)
    snap_id = db.append_snapshot(conn, as_of="2026-07-06T20:00:00Z", source="api_pull",
                                 cash_balance_eur=1000.0, created_at=now)
    db.append_positions(conn, snap_id, [dict(
        symbol="ADYEN", yf_ticker="ADYEN", instrument_type="stock", quantity=5.0,
        avg_open_price=None, native_currency="EUR", mv_native=4200.0, mv_eur=4200.0,
        weight=1.0, leverage=1.0)])
    conn.commit()
    lines = weekly.revalidation_lines(conn, as_of=SAT)
    assert any("ADYEN" in ln and "awaiting thesis ratification" in ln for ln in lines)


def test_outside_framework_holding_reported_by_design(tmp_db, fixed_clock):
    """An outside-framework holding with no thesis is reported as such (by design), not as a
    missing backfill — the thesis-less branch splits on framework_status (never silently
    skipped, never wrongly nagged to backfill)."""
    from agentcy import journal, mirror
    from agentcy.jobs import weekly
    from agentcy.journal import EntryIn
    conn = tmp_db
    now = db.to_iso(fixed_clock.now())
    je = journal.append(conn, EntryIn(decision_type="config_or_designation",
                                      decision_subtype="outside_framework",
                                      reasoning_at_the_moment="seed", actor="owner"),
                        clock=fixed_clock)
    snap_id = db.append_snapshot(conn, as_of="2026-07-06T20:00:00Z", source="api_pull",
                                 cash_balance_eur=1000.0, created_at=now)
    db.append_positions(conn, snap_id, [dict(
        symbol="VWRL", yf_ticker="VWRL", instrument_type="etf", quantity=5.0,
        avg_open_price=None, native_currency="EUR", mv_native=4200.0, mv_eur=4200.0,
        weight=1.0, leverage=1.0)])
    mirror.designate(conn, "VWRL", "outside_framework", journal_ref=je,
                     valid_from=db.to_iso(fixed_clock.now()))
    conn.commit()
    lines = weekly.revalidation_lines(conn, as_of=SAT)
    assert any("VWRL" in ln and "outside framework" in ln for ln in lines)
    assert not any("VWRL" in ln and "awaiting thesis ratification" in ln for ln in lines)


def test_intact_backfill_thesis_fires_via_existing_watchdog(tmp_db, fixed_clock, monkeypatch):
    """A ratified (intact) backfill thesis with a broken auto-trigger fires an alert through
    weekly.run_trigger_tests with NO Watchdog change beyond the RF2 draft-status guard (seeded,
    offline). Mirrors the onboarding path: run_backfill -> owner drafts real qualitative values
    (RF1) -> approve -> intact; then the SAME evaluator picks it up."""
    from agentcy import asks, backfill, journal, register, runlog
    from agentcy.jobs import weekly
    from agentcy.journal import EntryIn
    from agentcy.fetch import store
    from agentcy.freshness import Stamped, DataState
    conn = tmp_db
    now = db.to_iso(fixed_clock.now())
    journal.append(conn, EntryIn(decision_type="config_or_designation",
                                 decision_subtype="config_change",
                                 reasoning_at_the_moment="seed", actor="owner"),
                   clock=fixed_clock)
    snap_id = db.append_snapshot(conn, as_of="2026-07-06T20:00:00Z", source="api_pull",
                                 cash_balance_eur=1000.0, created_at=now)
    db.append_positions(conn, snap_id, [dict(
        symbol="ADYEN", yf_ticker="ADYEN", instrument_type="stock", quantity=5.0,
        avg_open_price=None, native_currency="EUR", mv_native=4200.0, mv_eur=4200.0,
        weight=1.0, leverage=1.0)])
    db.append_position_details(conn, snap_id, [dict(
        symbol="ADYEN", opened_at="2024-01-15T00:00:00Z", invested_native=3000.0,
        invested_eur=3000.0, unrealized_pnl_native=1200.0, unrealized_pnl_pct=40.0,
        current_rate=840.0, direction="buy", lot_count=2, raw_json="{}")])
    conn.commit()

    # baseline: margin baseline 30.0 -> margin_erosion floor 22.5 (comparator '<')
    def _stamped(v, state="fresh"):
        return Stamped(value=v, fetched_at=SAT, state=DataState(state), note=None)
    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: _stamped([("2026-06-30", 14.2)]), raising=False)
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: _stamped([("2026-06-30", 30.0)]), raising=False)
    monkeypatch.setattr(store, "balance_safety_series",
                        lambda c, t, *, as_of: _stamped([("2026-06-30", 1.5)]), raising=False)
    monkeypatch.setattr(store, "shares_yoy",
                        lambda c, t, *, as_of: _stamped(1.2), raising=False)
    monkeypatch.setattr(store, "owner_fcf_ttm", lambda c, t, *, as_of: None, raising=False)

    # onboard -> owner drafts real qualitative values (RF1) -> ratify -> intact
    results = backfill.run_backfill(conn, ticker="ADYEN", clock=fixed_clock, as_of=SAT)
    tid = results[0].thesis_id
    ask_id = results[0].ratify_ask_id
    je = journal.append(conn, EntryIn(
        decision_type="thesis_revision", thesis_ref=tid,
        reasoning_at_the_moment="owner + Claude drafted the qualitative thesis", actor="owner"),
        clock=fixed_clock)
    register.revise(conn, tid, {
        "conviction": "high",
        "moat_types": ("network_effects", "switching_costs"),
        "moat_evidence": "Single-integration lock-in; net revenue retention above 110%.",
        "business_model_2s": "Adyen is one global payments platform merchants integrate once.",
        "ten_year_statement": "In ten years Adyen still processes a widening share of commerce.",
    }, reason="owner ratification draft", actor="owner", journal_ref=je, clock=fixed_clock)
    out = asks.answer(conn, ask_id, choice="approve", clock=fixed_clock)
    asks.apply_consequence(conn, out, clock=fixed_clock)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "intact"

    # now BREAK the margin_erosion trigger: margin TTM collapses to 10% (< floor 22.5, '<' floor)
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: _stamped([("2026-03-31", 10.0), ("2026-06-30", 9.0)]),
                        raising=False)
    handle = runlog.start(conn, "weekly", "2026-07-11", clock=fixed_clock)
    res = weekly.run_trigger_tests(conn, run_id=handle.run_id, clock=fixed_clock)
    assert res["fired_alert_ids"]                                   # an alert fired
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "under_review"
