"""tests/test_backfill.py - backfill-thesis onboarding (agentcy layer)."""
from datetime import datetime, timezone

from agentcy import db

AS_OF = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)


def _seed_two_holdings(tmp_db, fixed_clock):
    """Snapshot with NVDA (has a thesis) + ADYEN (no thesis) + cash; ADYEN carries an
    invested-moment position_detail row."""
    from agentcy import journal, register
    from agentcy.journal import EntryIn
    from agentcy.register import ThesisFields, TriggerSpec
    conn = tmp_db
    now = db.to_iso(fixed_clock.now())
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    snap_id = db.append_snapshot(conn, as_of="2026-07-06T20:00:00Z", source="api_pull",
                                 cash_balance_eur=5000.0, created_at=now)
    db.append_positions(conn, snap_id, [
        dict(symbol="NVDA", yf_ticker="NVDA", instrument_type="stock", quantity=10.0,
             avg_open_price=100.0, native_currency="USD", mv_native=2000.0, mv_eur=1800.0,
             weight=0.30, leverage=1.0),
        dict(symbol="ADYEN", yf_ticker="ADYEN", instrument_type="stock", quantity=5.0,
             avg_open_price=None, native_currency="EUR", mv_native=4200.0, mv_eur=4200.0,
             weight=0.70, leverage=1.0)])
    db.append_position_details(conn, snap_id, [
        dict(symbol="ADYEN", opened_at="2024-01-15T00:00:00Z", invested_native=3000.0,
             invested_eur=3000.0, unrealized_pnl_native=1200.0, unrealized_pnl_pct=40.0,
             current_rate=840.0, direction="buy", lot_count=2, raw_json="{}")])
    # NVDA gets a live thesis so it is NOT thesis-less
    fields = ThesisFields(
        business_model_2s="a. b.", moat_types=("switching_costs",), moat_evidence="e",
        owner_earnings_json="{}", owner_earnings_narrative="n", value_at_purchase=None,
        fair_band_low=25.0, fair_band_high=35.0, denominator_note=None, conviction="high",
        mgmt_trust="neutral", mgmt_trust_note=None, circle_fit="core", circle_fit_note=None,
        ten_year_statement="t", status_buy_flag=False, status_buy_note=None)
    trigs = [
        TriggerSpec(type="growth_floor", statement="s", metric="revenue_yoy", comparator="<",
                    threshold=10.0, moat_link=None, persistence="2_consecutive_quarters"),
        TriggerSpec(type="margin_erosion", statement="s", metric="owner_fcf_margin",
                    comparator="<", threshold=20.0, moat_link="switching_costs",
                    persistence="ttm")]
    tid = register.create_thesis(conn, ticker="NVDA", origin="gate", fields=fields,
                                 triggers=trigs, journal_ref=je, clock=fixed_clock)
    register.activate(conn, tid, cause="seed", clock=fixed_clock)
    conn.commit()
    return conn


def test_detect_thesis_less_returns_only_undressed_holding(tmp_db, fixed_clock):
    from agentcy import backfill
    conn = _seed_two_holdings(tmp_db, fixed_clock)
    found = backfill.detect_thesis_less(conn, as_of=AS_OF)
    assert [h.symbol for h in found] == ["ADYEN"]
    h = found[0]
    assert h.yf_ticker == "ADYEN" and h.quantity == 5.0
    assert h.opened_at == "2024-01-15T00:00:00Z" and h.invested_eur == 3000.0


def test_detect_skips_cash(tmp_db, fixed_clock):
    from agentcy import backfill
    conn = _seed_two_holdings(tmp_db, fixed_clock)
    # a cash position is never onboarded
    snap = db.fetch_latest_snapshot(conn)
    assert all(h.instrument_type != "cash" for h in backfill.detect_thesis_less(conn, as_of=AS_OF))


def _stub_store(monkeypatch, *, rev=None, margin=None, ndte=None, shares=None, oe_json=None):
    from agentcy.fetch import store
    from agentcy.freshness import Stamped, DataState

    def _stamped(value, state="fresh"):
        return Stamped(value=value, fetched_at=AS_OF, state=DataState(state), note=None)

    monkeypatch.setattr(store, "revenue_yoy_series",
                        lambda c, t, *, as_of: (_stamped(rev) if rev is not None else None),
                        raising=False)
    monkeypatch.setattr(store, "margin_series",
                        lambda c, t, *, as_of: (_stamped(margin) if margin is not None else None),
                        raising=False)
    monkeypatch.setattr(store, "balance_safety_series",
                        lambda c, t, *, as_of: (_stamped(ndte) if ndte is not None else None),
                        raising=False)
    monkeypatch.setattr(store, "shares_yoy",
                        lambda c, t, *, as_of: (_stamped(shares) if shares is not None else None),
                        raising=False)

    class _OE:
        def usable(self): return oe_json is not None
    monkeypatch.setattr(store, "owner_fcf_ttm",
                        lambda c, t, *, as_of: (object() if False else None), raising=False)


def test_baseline_full(tmp_db, fixed_clock, monkeypatch):
    from agentcy import backfill
    _stub_store(monkeypatch,
                rev=[("2026-06-30", 14.2)], margin=[("2026-06-30", 30.0)],
                ndte=[("2026-06-30", 1.5)], shares=1.2)
    b = backfill.compute_baseline(tmp_db, "ADYEN", as_of=AS_OF)
    assert b.revenue_yoy == 14.2 and b.owner_fcf_margin == 30.0
    assert b.net_debt_ebitda == 1.5 and b.shares_yoy == 1.2
    assert b.owner_earnings_json == "{}"


def test_baseline_thin_legs_are_none(tmp_db, fixed_clock, monkeypatch):
    from agentcy import backfill
    _stub_store(monkeypatch, rev=None, margin=[("2026-06-30", 25.0)], ndte=None, shares=None)
    b = backfill.compute_baseline(tmp_db, "ADYEN", as_of=AS_OF)
    assert b.revenue_yoy is None and b.owner_fcf_margin == 25.0
    assert b.net_debt_ebitda is None and b.shares_yoy is None
