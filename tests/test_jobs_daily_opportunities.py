"""P6.5: E.4 daily comparisons — on_sale (held intact), fair_entry (WATCH), MA-3 suspension."""
from datetime import datetime, timezone

from agentcy import db
from agentcy.freshness import DataState, Stamped


def _stamp(value, state=DataState.FRESH):
    return Stamped(value=value, fetched_at=datetime(2026, 7, 4, tzinfo=timezone.utc), state=state)


def test_on_sale_line_for_held_intact_thesis(seeded_portfolio, fixed_clock, monkeypatch):
    from agentcy.fetch import store
    from agentcy.jobs import daily
    conn = seeded_portfolio["conn"]
    monkeypatch.setattr(store, "denominator_per_share", lambda c, t, *, as_of: _stamp(20.0))
    # price 500 / denom 20 = 25x; band 25-35, mid 30; opportunity <= 0.8*30 = 24 -> NOT on sale
    lines, more = daily.opportunity_lines(conn, as_of=fixed_clock.now())
    assert lines == () and more == 0
    # drop the price to 450 -> 22.5x <= 24x -> ON SALE
    db.append_price_rows(conn, [dict(yf_ticker="MSFT", bar_date="2026-07-07", close=450.0,
                                     adj_close=450.0, dividend=0.0, currency="USD",
                                     fetched_at=db.to_iso(fixed_clock.now()), run_id=None)])
    lines, more = daily.opportunity_lines(conn, as_of=fixed_clock.now())
    assert len(lines) == 1 and more == 0
    line = lines[0]
    assert line.kind == "on_sale" and line.ticker == "MSFT"
    assert abs(line.multiple - 22.5) < 1e-9
    assert (line.band_low, line.band_high) == (25.0, 35.0)
    assert line.triggers_total == 2 and line.suspended_note is None


def test_stale_denominator_suspends_with_note_never_silent(seeded_portfolio, fixed_clock, monkeypatch):
    from agentcy.fetch import store
    from agentcy.jobs import daily
    monkeypatch.setattr(store, "denominator_per_share",
                        lambda c, t, *, as_of: _stamp(20.0, DataState.STALE))
    lines, _ = daily.opportunity_lines(seeded_portfolio["conn"], as_of=fixed_clock.now())
    assert len(lines) == 1
    assert lines[0].multiple is None
    assert lines[0].suspended_note and "suspended" in lines[0].suspended_note  # MA-3: stated, never silent


def test_fair_entry_fires_for_watch_items_only(seeded_portfolio, fixed_clock, monkeypatch):
    from agentcy import journal, register
    from agentcy.fetch import store
    from agentcy.jobs import daily
    from agentcy.journal import EntryIn
    from agentcy.register import ThesisFields, TriggerSpec
    conn = seeded_portfolio["conn"]
    je = journal.append(conn, EntryIn(decision_type="gate_verdict", decision_subtype="watch",
                                      ticker="ADBE", reasoning_at_the_moment="test",
                                      actor="owner"), clock=fixed_clock)
    fields = ThesisFields(
        business_model_2s="Sells creative software subscriptions. Workflow lock-in is the moat.",
        moat_types=("switching_costs",), moat_evidence="file-format ecosystem",
        owner_earnings_json="{}", owner_earnings_narrative="solid",
        value_at_purchase=None, fair_band_low=18.0, fair_band_high=26.0,
        denominator_note=None, conviction="medium", mgmt_trust="trusted_professional",
        mgmt_trust_note=None, circle_fit="core", circle_fit_note=None,
        ten_year_statement="Creative tooling compounds for a decade.",
        status_buy_flag=False, status_buy_note=None)
    trigs = [TriggerSpec(type="growth_floor", statement="If revenue YoY < 8% for 2 quarters, growth story is over.",
                         metric="revenue_yoy", comparator="<", threshold=8.0,
                         moat_link="switching_costs", persistence="2_consecutive_quarters"),
             TriggerSpec(type="owner_attested_event", statement="Has the CEO departed or announced departure?",
                         metric=None, comparator=None, threshold=None, moat_link=None,
                         persistence="single_observation", yes_means="fire")]
    tid = register.create_thesis(conn, ticker="ADBE", origin="gate", fields=fields,
                                 triggers=trigs, journal_ref=je, clock=fixed_clock)  # stays draft (WATCH)
    conn.execute("INSERT INTO watchlist_item (ticker, added_at, idea_source, one_line_why, stage,"
                 " stage_changed_at, thesis_ref) VALUES (?,?,?,?,?,?,?)",
                 ("ADBE", db.to_iso(fixed_clock.now()), "own_research", "why",
                  "gate_approved_waiting", db.to_iso(fixed_clock.now()), tid))
    db.append_price_rows(conn, [dict(yf_ticker="ADBE", bar_date="2026-07-07", close=480.0,
                                     adj_close=480.0, dividend=0.0, currency="USD",
                                     fetched_at=db.to_iso(fixed_clock.now()), run_id=None)])
    monkeypatch.setattr(store, "denominator_per_share", lambda c, t, *, as_of: _stamp(20.0))
    lines, _ = daily.opportunity_lines(conn, as_of=fixed_clock.now())
    fe = [l for l in lines if l.kind == "fair_entry"]
    assert len(fe) == 1 and fe[0].ticker == "ADBE"
    assert abs(fe[0].multiple - 24.0) < 1e-9              # 480/20 = 24x <= band_high 26x
