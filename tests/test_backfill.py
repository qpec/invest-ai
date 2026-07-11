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
    # Comparators are the FIRE condition (triggers._breaches returns `value cmp threshold`),
    # matching the canonical gate-created forms in test_triggers.py: floors fire on '<',
    # ceilings fire on '>'. The end-to-end FIRE/PASS test below proves these actually fire.
    assert by_type["growth_floor"].comparator == "<"
    assert round(by_type["growth_floor"].threshold, 4) == round(14.2 - 10.0, 4)
    assert by_type["margin_erosion"].comparator == "<"
    assert round(by_type["margin_erosion"].threshold, 4) == round(30.0 * 0.75, 4)
    assert by_type["margin_erosion"].moat_link == "switching_costs"
    assert by_type["balance_sheet_safety"].comparator == ">"
    assert by_type["balance_sheet_safety"].threshold == min(1.5 + 1.0, 4.0)
    assert by_type["dilution"].comparator == ">" and by_type["dilution"].threshold == 5.0
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


def _backfill_fields():
    from agentcy.register import ThesisFields
    return ThesisFields(
        business_model_2s="a. b.", moat_types=("switching_costs",), moat_evidence="e",
        owner_earnings_json="{}", owner_earnings_narrative="n", value_at_purchase=None,
        fair_band_low=25.0, fair_band_high=35.0, denominator_note=None, conviction="high",
        mgmt_trust="neutral", mgmt_trust_note=None, circle_fit="core", circle_fit_note=None,
        ten_year_statement="t", status_buy_flag=False, status_buy_note=None)


def _armed_backfill_triggers(tmp_db, fixed_clock):
    """derive -> commit (via create_thesis) -> activate: the real onboarding path, returning
    the four armed derived triggers keyed by type."""
    from agentcy import backfill, journal, register
    from agentcy.journal import EntryIn
    je = journal.append(tmp_db, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    specs = backfill.derive_triggers(_baseline())          # rev 14.2, margin 30, ndte 1.5, shares 1.2
    tid = register.create_thesis(tmp_db, ticker="ADYEN", origin="backfill",
                                 fields=_backfill_fields(), triggers=specs, journal_ref=je,
                                 clock=fixed_clock)
    register.activate(tmp_db, tid, cause="backfill confirmed", clock=fixed_clock)
    return {t["type"]: t for t in db.fetch_armed_triggers(tmp_db, tid)}


def test_derived_triggers_fire_on_deterioration_and_pass_when_healthy(
        tmp_db, fixed_clock, monkeypatch, stamped):
    """End-to-end guard against comparator inversion: each derived trigger is committed through
    register + armed, then evaluated against BOTH a deteriorating series (must FIRE) and a
    healthy one (must PASS). Thresholds from _baseline(): growth floor 4.2%, margin floor 22.5%,
    net-debt/EBITDA ceiling 2.5x, dilution ceiling 5%/yr."""
    from agentcy import triggers
    from agentcy.fetch import store
    armed = _armed_backfill_triggers(tmp_db, fixed_clock)

    def _set(name, value):
        monkeypatch.setattr(store, name, lambda c, t, *, as_of: stamped(value), raising=False)

    # --- growth_floor: floor = 14.2 - 10 = 4.2, fires when revenue_yoy < 4.2 for 2 quarters ---
    _set("revenue_yoy_series", [("2026-03-31", 2.0), ("2026-06-30", 1.5)])   # collapse below floor
    assert triggers.evaluate(tmp_db, armed["growth_floor"], as_of=AS_OF).result == "FIRE"
    _set("revenue_yoy_series", [("2026-03-31", 18.0), ("2026-06-30", 20.0)])  # healthy > floor
    assert triggers.evaluate(tmp_db, armed["growth_floor"], as_of=AS_OF).result == "PASS"

    # --- margin_erosion: floor = 30 * 0.75 = 22.5, fires when margin < 22.5 for 2 quarters ---
    _set("margin_series", [("2026-03-31", 18.0), ("2026-06-30", 17.0)])       # eroded below floor
    assert triggers.evaluate(tmp_db, armed["margin_erosion"], as_of=AS_OF).result == "FIRE"
    _set("margin_series", [("2026-03-31", 30.0), ("2026-06-30", 31.0)])       # healthy > floor
    assert triggers.evaluate(tmp_db, armed["margin_erosion"], as_of=AS_OF).result == "PASS"

    # --- balance_sheet_safety: ceiling = min(1.5+1, 4) = 2.5, fires when net_debt/EBITDA > 2.5 ---
    _set("balance_safety_series", [("2026-03-31", 5.0), ("2026-06-30", 6.0)])  # levered above ceil
    assert triggers.evaluate(tmp_db, armed["balance_sheet_safety"], as_of=AS_OF).result == "FIRE"
    _set("balance_safety_series", [("2026-03-31", 1.5), ("2026-06-30", 1.2)])  # safe < ceiling
    assert triggers.evaluate(tmp_db, armed["balance_sheet_safety"], as_of=AS_OF).result == "PASS"

    # --- dilution (ttm scalar): ceiling 5%/yr, fires when shares_yoy > 5 ---
    _set("shares_yoy", 10.0)                                                   # 10%/yr dilution
    assert triggers.evaluate(tmp_db, armed["dilution"], as_of=AS_OF).result == "FIRE"
    _set("shares_yoy", 1.0)                                                    # 1%/yr, healthy
    assert triggers.evaluate(tmp_db, armed["dilution"], as_of=AS_OF).result == "PASS"


def test_create_backfill_draft_origin_and_status(tmp_db, fixed_clock):
    from agentcy import backfill
    from agentcy import journal
    from agentcy.journal import EntryIn
    conn = tmp_db
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    held = backfill.HeldWithoutThesis(symbol="ADYEN", yf_ticker="ADYEN",
                                      instrument_type="stock", quantity=5.0,
                                      opened_at="2024-01-15T00:00:00Z", invested_eur=3000.0)
    baseline = backfill.Baseline(yf_ticker="ADYEN", revenue_yoy=14.2, owner_fcf_margin=30.0,
                                 net_debt_ebitda=1.5, shares_yoy=1.2, owner_earnings_json="{}")
    tid = backfill.create_backfill_draft(conn, held, baseline, journal_ref=je, clock=fixed_clock)
    assert tid == "TH-ADYEN-001"
    assert db.fetch_thesis(conn, tid)["origin"] == "backfill"
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "draft"   # NOT monitored
    assert len(db.fetch_armed_triggers(conn, tid)) == 4
    tv = db.fetch_current_thesis_version(conn, tid)
    assert tv["value_at_purchase"] is None                  # cost basis quarantined at v1
    assert "(draft - pending ratification)" in tv["business_model_2s"]


def test_create_backfill_draft_bootstrapping_when_no_triggers(tmp_db, fixed_clock):
    from agentcy import backfill, journal
    from agentcy.journal import EntryIn
    conn = tmp_db
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    held = backfill.HeldWithoutThesis(symbol="THIN", yf_ticker="THIN", instrument_type="stock",
                                      quantity=1.0, opened_at=None, invested_eur=None)
    # only a growth_floor leg computable -> 1 trigger, no moat link -> cannot form a thesis
    baseline = backfill.Baseline(yf_ticker="THIN", revenue_yoy=14.2, owner_fcf_margin=None,
                                 net_debt_ebitda=None, shares_yoy=None, owner_earnings_json="{}")
    tid = backfill.create_backfill_draft(conn, held, baseline, journal_ref=je, clock=fixed_clock)
    assert tid is None
    assert db.fetch_theses(conn) == []


# --- Task 5: the Telegram ratification ask (approve/edit -> intact/draft) ------------

def _seed_draft(conn, fixed_clock):
    """Create the origin='backfill' DRAFT thesis with the documented placeholder qualitative
    fields (the deterministic scaffolding; conviction='medium', business/moat/ten-year draft)."""
    from agentcy import backfill, journal
    from agentcy.journal import EntryIn
    je = journal.append(conn, EntryIn(
        decision_type="config_or_designation", decision_subtype="config_change",
        reasoning_at_the_moment="seed", actor="owner"), clock=fixed_clock)
    held = backfill.HeldWithoutThesis(symbol="ADYEN", yf_ticker="ADYEN", instrument_type="stock",
                                      quantity=5.0, opened_at="2024-01-15T00:00:00Z",
                                      invested_eur=3000.0)
    baseline = backfill.Baseline(yf_ticker="ADYEN", revenue_yoy=14.2, owner_fcf_margin=30.0,
                                 net_debt_ebitda=1.5, shares_yoy=1.2, owner_earnings_json="{}")
    tid = backfill.create_backfill_draft(conn, held, baseline, journal_ref=je, clock=fixed_clock)
    return tid, held


def _apply_real_ratification(conn, tid, fixed_clock, *, conviction="high"):
    """Simulate the claudeclaw qualitative draft + owner ratification (RF1): register.revise
    the placeholder qualitative fields to REAL owner values BEFORE approve. This is what the
    Part-B drafting round / desk supplies so approve is not activating placeholders as judgment."""
    from agentcy import journal, register
    from agentcy.journal import EntryIn
    je = journal.append(conn, EntryIn(
        decision_type="thesis_revision", thesis_ref=tid,
        reasoning_at_the_moment="owner + Claude drafted the qualitative thesis", actor="owner"),
        clock=fixed_clock)
    register.revise(conn, tid, {
        "conviction": conviction,
        "moat_types": ("network_effects", "switching_costs"),
        "moat_evidence": "Single-integration lock-in; net revenue retention consistently above 110%.",
        "business_model_2s": "Adyen is a single global payments platform. Merchants integrate once.",
        "ten_year_statement": "In ten years Adyen still processes a widening share of global commerce.",
    }, reason="owner ratification draft", actor="owner", journal_ref=je, clock=fixed_clock)


def test_ratify_approve_activates_and_arms(tmp_db, fixed_clock):
    from agentcy import asks, backfill
    conn = tmp_db
    tid, held = _seed_draft(conn, fixed_clock)
    ask = backfill.mint_ratify_ask(conn, tid, held, clock=fixed_clock)
    assert ask.kind == "N" and ask.options == ("approve", "edit") and ask.thesis_ref == tid
    # RF1: the owner supplies real conviction/qualitative values (the claudeclaw draft) BEFORE
    # approve; only then does approve promote the thesis to intact.
    _apply_real_ratification(conn, tid, fixed_clock, conviction="high")
    out = asks.answer(conn, ask.ask_id, choice="approve", clock=fixed_clock)
    assert out.consequence == "note.approve"
    asks.apply_consequence(conn, out, clock=fixed_clock)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "intact"   # monitored now
    assert len(db.fetch_armed_triggers(conn, tid)) == 4


def test_ratify_approve_with_placeholder_still_in_place_is_refused(tmp_db, fixed_clock):
    """RF1 (BLOCKING, FR9): approve while conviction is still the 'medium' placeholder AND no
    real conviction/qualitative values were supplied is REFUSED — the thesis stays draft and
    UNmonitored. Never render system-chosen placeholders as the owner's judgment."""
    from agentcy import asks, backfill
    conn = tmp_db
    tid, held = _seed_draft(conn, fixed_clock)
    ask = backfill.mint_ratify_ask(conn, tid, held, clock=fixed_clock)
    out = asks.answer(conn, ask.ask_id, choice="approve", clock=fixed_clock)
    note = asks.apply_consequence(conn, out, clock=fixed_clock)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "draft"   # NOT activated
    assert db.fetch_current_thesis_version(conn, tid)["version"] == 1        # not revised
    assert note is not None and "draft" in note.lower()


def test_ratify_approve_allows_genuine_medium_once_rationale_drafted(tmp_db, fixed_clock):
    """RF1 conjunction: a genuine 'medium' conviction is NOT a placeholder once the owner has
    drafted the real business-model / ten-year rationale (the '(draft ...)' sentinel is gone).
    Approve then activates - a real 'medium' is owner judgment, not the neutral default."""
    from agentcy import asks, backfill, journal, register
    from agentcy.journal import EntryIn
    conn = tmp_db
    tid, held = _seed_draft(conn, fixed_clock)
    je = journal.append(conn, EntryIn(
        decision_type="thesis_revision", thesis_ref=tid,
        reasoning_at_the_moment="owner drafted the rationale, kept conviction medium",
        actor="owner"), clock=fixed_clock)
    register.revise(conn, tid, {
        "conviction": "medium",   # deliberately kept medium - but the rationale is now real
        "moat_evidence": "Single-integration lock-in; net revenue retention above 110%.",
        "business_model_2s": "Adyen is one global payments platform merchants integrate once.",
        "ten_year_statement": "In ten years Adyen still processes a widening share of commerce."},
        reason="owner ratification draft", actor="owner", journal_ref=je, clock=fixed_clock)
    ask = backfill.mint_ratify_ask(conn, tid, held, clock=fixed_clock)
    out = asks.answer(conn, ask.ask_id, choice="approve", clock=fixed_clock)
    asks.apply_consequence(conn, out, clock=fixed_clock)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "intact"   # activated


def test_ratify_approve_refused_when_only_conviction_is_real(tmp_db, fixed_clock):
    """RF1 (BLOCKING, FR9): supplying a real, non-'medium' conviction (e.g. 'high') does NOT
    license activating while the Claude-drafted moat / business-model / ten-year are STILL the
    '(draft ...)' sentinel. The earlier 'conviction == medium AND ...' conjunction let this through
    -> the literal '(draft - pending ratification)' would surface as owner judgment in the weekly
    ten-year alert span and the archive '## Moat' section once intact. Approve MUST refuse; the
    thesis stays draft and UNmonitored until every qualitative field carries a real value."""
    from agentcy import asks, backfill, journal, register
    from agentcy.journal import EntryIn
    conn = tmp_db
    tid, held = _seed_draft(conn, fixed_clock)
    je = journal.append(conn, EntryIn(
        decision_type="thesis_revision", thesis_ref=tid,
        reasoning_at_the_moment="owner set conviction high but left the rationale as draft",
        actor="owner"), clock=fixed_clock)
    register.revise(conn, tid, {"conviction": "high"},   # only conviction; sentinels untouched
                    reason="conviction only", actor="owner", journal_ref=je, clock=fixed_clock)
    ask = backfill.mint_ratify_ask(conn, tid, held, clock=fixed_clock)
    out = asks.answer(conn, ask.ask_id, choice="approve", clock=fixed_clock)
    note = asks.apply_consequence(conn, out, clock=fixed_clock)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "draft"   # NOT activated
    assert note is not None and "draft" in note.lower()


def test_ratify_approve_refused_when_only_moat_evidence_left_draft(tmp_db, fixed_clock):
    """RF1: even with a real conviction AND real business-model / ten-year text, leaving
    moat_evidence as the '(draft ...)' sentinel must still REFUSE activation - that literal text
    would otherwise render in the archive '## Moat' section as owner judgment (FR9)."""
    from agentcy import asks, backfill, journal, register
    from agentcy.journal import EntryIn
    conn = tmp_db
    tid, held = _seed_draft(conn, fixed_clock)
    je = journal.append(conn, EntryIn(
        decision_type="thesis_revision", thesis_ref=tid,
        reasoning_at_the_moment="owner drafted business/ten-year but not the moat evidence",
        actor="owner"), clock=fixed_clock)
    register.revise(conn, tid, {
        "conviction": "high",
        "business_model_2s": "Adyen is one global payments platform merchants integrate once.",
        "ten_year_statement": "In ten years Adyen still processes a widening share of commerce."},
        reason="rationale minus moat", actor="owner", journal_ref=je, clock=fixed_clock)
    ask = backfill.mint_ratify_ask(conn, tid, held, clock=fixed_clock)
    out = asks.answer(conn, ask.ask_id, choice="approve", clock=fixed_clock)
    note = asks.apply_consequence(conn, out, clock=fixed_clock)
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "draft"   # NOT activated
    assert note is not None and "draft" in note.lower()


def test_ratify_edit_keeps_draft(tmp_db, fixed_clock):
    from agentcy import asks, backfill
    conn = tmp_db
    tid, held = _seed_draft(conn, fixed_clock)
    ask = backfill.mint_ratify_ask(conn, tid, held, clock=fixed_clock)
    out = asks.answer(conn, ask.ask_id, choice="edit",
                      text="conviction should be high; add an owner-attested CEO trigger",
                      clock=fixed_clock)
    assert out.consequence == "note.edit"
    asks.apply_consequence(conn, out, clock=fixed_clock, evidence=out.ask.answer.get("text"))
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "draft"   # still not monitored


def test_ratify_edit_records_owner_text_verbatim(tmp_db, fixed_clock):
    """RF4: the owner's edit text is captured (via the free-text reply / ForceReply), journaled
    verbatim, so the Part-B drafting round has it. A bare tap that carried no text never fabricates
    an empty edit into an activation."""
    from agentcy import asks, backfill
    conn = tmp_db
    tid, held = _seed_draft(conn, fixed_clock)
    ask = backfill.mint_ratify_ask(conn, tid, held, clock=fixed_clock)
    text = "raise conviction to high and add a regulatory-barrier moat leg"
    out = asks.answer(conn, ask.ask_id, choice="edit", text=text, clock=fixed_clock)
    asks.apply_consequence(conn, out, clock=fixed_clock, evidence=out.ask.answer.get("text"))
    th = db.fetch_thesis(conn, tid)
    entries = [e for e in db.fetch_journal_entries(conn, decision_type="config_or_designation")
               if e["thesis_ref"] == tid and e["ask_ref"] == ask.ask_id]
    assert entries and entries[-1]["reasoning_at_the_moment"] == text
    assert db.fetch_current_thesis_status(conn, tid)["status"] == "draft"
