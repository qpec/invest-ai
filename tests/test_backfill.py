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


def _stub_store(monkeypatch, *, rev=None, margin=None, ndte=None, shares=None, oe=None):
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
    monkeypatch.setattr(store, "owner_fcf_ttm",
                        lambda c, t, *, as_of: (_stamped(oe) if oe is not None else None),
                        raising=False)


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


def test_baseline_owner_earnings_json_is_pinned_with_provenance(tmp_db, fixed_clock, monkeypatch):
    """A usable owner-earnings Stamped serializes via the Gate's canonical helper, so the
    backfill JSON carries the six pinned fields PLUS the fetched_at provenance stamp
    (MA-11) - identical to a gate-origin thesis, never provenance-stripped."""
    import json

    from agentcy import backfill, gate
    from agentcy.fetch.store import OwnerEarnings
    oe = OwnerEarnings(
        fcf_ttm=1000.0, sbc_ttm=200.0, owner_fcf_ttm=800.0,
        owner_fcf_per_share_ttm=8.0, owner_fcf_margin_ttm=32.0,
        periods_used=("2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"))
    _stub_store(monkeypatch, rev=[("2026-06-30", 14.2)], oe=oe)
    b = backfill.compute_baseline(tmp_db, "ADYEN", as_of=AS_OF)
    payload = json.loads(b.owner_earnings_json)
    assert payload["fcf_ttm"] == 1000.0 and payload["sbc_ttm"] == 200.0
    assert payload["owner_fcf_ttm"] == 800.0
    assert payload["owner_fcf_per_share_ttm"] == 8.0
    assert payload["owner_fcf_margin_ttm"] == 32.0
    assert payload["periods_used"] == list(oe.periods_used)
    # the provenance stamp the hand-rolled dict omitted; Z-suffixed like the gate path
    assert payload["fetched_at"] == "2026-07-08T05:00:00Z"
    # byte-identical to what the Gate would emit for the same Stamped -> no drift
    from agentcy.freshness import Stamped, DataState
    stamped = Stamped(value=oe, fetched_at=AS_OF, state=DataState("fresh"), note=None)
    assert b.owner_earnings_json == gate._oe_json(stamped)


def _baseline(**kw):
    from agentcy import backfill
    base = dict(yf_ticker="ADYEN", revenue_yoy=14.2, owner_fcf_margin=30.0,
                net_debt_ebitda=1.5, shares_yoy=1.2, owner_earnings_json="{}")
    base.update(kw)
    return backfill.Baseline(**base)


def test_derive_four_triggers_exact_thresholds():
    from agentcy import backfill
    specs = backfill.derive_triggers(_baseline())
    by_type = {s.type: s for s in specs}
    assert set(by_type) == {"growth_floor", "margin_erosion",
                            "balance_sheet_safety", "dilution"}
    assert by_type["growth_floor"].comparator == ">"
    assert round(by_type["growth_floor"].threshold, 4) == round(14.2 - 10.0, 4)
    assert by_type["margin_erosion"].comparator == ">"
    assert round(by_type["margin_erosion"].threshold, 4) == round(30.0 * 0.75, 4)
    assert by_type["margin_erosion"].moat_link == "switching_costs"
    assert by_type["balance_sheet_safety"].comparator == "<"
    assert by_type["balance_sheet_safety"].threshold == min(1.5 + 1.0, 4.0)
    assert by_type["dilution"].comparator == "<" and by_type["dilution"].threshold == 5.0
    assert by_type["dilution"].persistence == "ttm"


def test_balance_ndte_caps_at_four():
    from agentcy import backfill
    specs = backfill.derive_triggers(_baseline(net_debt_ebitda=8.0))
    ndte = next(s for s in specs if s.type == "balance_sheet_safety")
    assert ndte.threshold == 4.0   # min(8.0 + 1.0, 4.0)


def test_derive_omits_uncomputable_legs():
    from agentcy import backfill
    specs = backfill.derive_triggers(_baseline(revenue_yoy=None, shares_yoy=None))
    types = {s.type for s in specs}
    assert types == {"margin_erosion", "balance_sheet_safety"}   # rev + dilution omitted
    assert any(s.moat_link for s in specs)   # BUF-4 still satisfiable


def test_derive_series_triggers_get_two_quarter_persistence():
    from agentcy import backfill
    specs = {s.type: s for s in backfill.derive_triggers(_baseline())}
    for t in ("growth_floor", "margin_erosion", "balance_sheet_safety"):
        assert specs[t].persistence == "2_consecutive_quarters"


def test_bootstrapping_when_only_non_moat_legs_compute():
    """RF5: >=2 legs compute but the moat-linked margin_erosion is absent -> the triggers do
    NOT form a thesis (moat-link guard, BUF-4), so onboarding is reported BOOTSTRAPPING rather
    than minting a moat-linkless thesis."""
    from agentcy import backfill
    # margin (the only moat-linked leg) is absent; growth + balance + dilution compute
    specs = backfill.derive_triggers(_baseline(owner_fcf_margin=None))
    assert len(specs) >= 2                       # enough legs by count alone
    assert not any(s.moat_link for s in specs)   # ... but none carries a moat link
    assert backfill._triggers_form_a_thesis(specs) is False
