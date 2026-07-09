"""tests/test_study.py — F.3 The Study."""
import pytest

from agentcy import db


def _thesis(tmp_db, fixed_clock, ticker):
    from agentcy import register
    fields = register.ThesisFields(
        business_model_2s=f"{ticker} does one thing. It does it well.",
        moat_types=("brand_trust",), moat_evidence="e", owner_earnings_json="{}",
        owner_earnings_narrative="n", value_at_purchase=None, fair_band_low=20.0,
        fair_band_high=30.0, denominator_note=None, conviction="high", mgmt_trust="neutral",
        mgmt_trust_note=None, circle_fit="core", circle_fit_note=None,
        ten_year_statement="t", status_buy_flag=False, status_buy_note=None)
    ts = [register.TriggerSpec(type="growth_floor", statement="s", metric="revenue_yoy",
            comparator="<", threshold=10.0, moat_link=None, persistence="single_observation"),
          register.TriggerSpec(type="margin_erosion", statement="s", metric="m", comparator="<",
            threshold=20.0, moat_link="brand_trust", persistence="ttm")]
    tid = register.create_thesis(tmp_db, ticker=ticker, origin="gate", fields=fields,
                                 triggers=ts, journal_ref=1, clock=fixed_clock)
    register.activate(tmp_db, tid, cause="c", clock=fixed_clock)
    return tid


def test_build_digest_picks_next_and_has_no_performance(tmp_db, fixed_clock):
    from agentcy import study
    _thesis(tmp_db, fixed_clock, "VEEV")
    _thesis(tmp_db, fixed_clock, "CRWD")
    ctx = study.build_digest(tmp_db, as_of=fixed_clock.now())
    assert ctx.restudy_ticker == "VEEV"                    # first, pointer starts NULL
    assert "VEEV" in ctx.restudy_excerpt and ctx.restudy_question
    assert ctx.mental_model_prompt
    assert not hasattr(ctx, "performance") and not hasattr(ctx, "return_pct")


def test_rotation_advances_and_wraps(tmp_db, fixed_clock):
    from agentcy import study
    _thesis(tmp_db, fixed_clock, "VEEV")
    _thesis(tmp_db, fixed_clock, "CRWD")
    ctx = study.build_digest(tmp_db, as_of=fixed_clock.now())
    study.advance_rotation(tmp_db, thesis_id=None, model_index=1, clock=fixed_clock)  # after VEEV
    # re-derive from state: next is CRWD
    st = db.fetch_study_state(tmp_db)
    assert st["mental_model_index"] == 1


def test_build_digest_respects_pointer(tmp_db, fixed_clock):
    from agentcy import study
    v = _thesis(tmp_db, fixed_clock, "VEEV")
    _thesis(tmp_db, fixed_clock, "CRWD")
    db.update_study_state(tmp_db, last_restudied_thesis_id=v, mental_model_index=0,
                          updated_at=db.to_iso(fixed_clock.now()))
    ctx = study.build_digest(tmp_db, as_of=fixed_clock.now())
    assert ctx.restudy_ticker == "CRWD"                    # next after VEEV


def test_record_note_appends(tmp_db, fixed_clock):
    from agentcy import study
    nid = study.record_note(tmp_db, kind="circle_note", text="learned about GxP validation",
                            ask_ref=None, clock=fixed_clock)
    assert nid == 1
