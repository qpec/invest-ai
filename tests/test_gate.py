"""tests/test_gate.py — Gate, watchlist, and gate-session behavior (P4)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agentcy import db


def test_append_gate_session_row(tmp_db):
    sid = db.append_gate_session(tmp_db, ticker="VEEV", mode="gate",
                                 started_at="2026-07-08T05:00:00Z")
    row = db.fetch_active_gate_session(tmp_db, "VEEV")
    assert row is not None
    assert row["session_id"] == sid
    assert row["step"] == "circle"          # DDL default
    assert row["state_json"] == "{}"        # DDL default
    assert row["status"] == "active"        # DDL default
    assert row["mode"] == "gate"


def test_gate_session_identity_guarded(tmp_db):
    db.append_gate_session(tmp_db, ticker="VEEV", mode="gate",
                           started_at="2026-07-08T05:00:00Z")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.execute("UPDATE gate_session SET ticker='MSFT' WHERE session_id=1")


def test_append_watchlist_item_row(tmp_db):
    item_id = db.append_watchlist_item(tmp_db, ticker="VEEV",
                                       added_at="2026-07-08T05:00:00Z",
                                       idea_source="own_research",
                                       one_line_why="validated GxP record layer")
    rows = db.fetch_watchlist(tmp_db, stage="raw")
    assert [r["item_id"] for r in rows] == [item_id]
    assert rows[0]["one_line_why"] == "validated GxP record layer"


# --- P4.2 circle step ---------------------------------------------------------

class ScriptedAsker:
    """Injected ask_owner: pops pre-scripted answers, logs every prompt (FR9 test seam)."""
    def __init__(self, answers):
        self.answers = list(answers)
        self.log = []

    def __call__(self, prompt, options=None):
        self.log.append((prompt, tuple(options) if options else None))
        return self.answers.pop(0)


TWO_SENTENCES = ("Veeva sells the system-of-record SaaS suite that life-sciences "
                 "companies run regulated core processes on. Customers pay recurring "
                 "subscriptions and effectively cannot leave.")
THREE_SENTENCES = TWO_SENTENCES + " Also it is great."


def test_sentence_count():
    from agentcy.gate import sentence_count
    assert sentence_count(TWO_SENTENCES) == 2
    assert sentence_count(THREE_SENTENCES) == 3
    assert sentence_count("One sentence without a period") == 1


def test_circle_step_happy_path():
    from agentcy.gate import step_circle
    state = {}
    ask = ScriptedAsker([TWO_SENTENCES, "validated-system switching costs", "core"])
    assert step_circle(state, ask) == "hell_no"
    assert state["business_model_2s"] == TWO_SENTENCES
    assert state["circle_fit_initial"] == "core"
    assert "pending_pass" not in state


def test_circle_step_rejects_three_sentences_then_accepts_two():
    from agentcy.gate import step_circle
    state = {}
    ask = ScriptedAsker([THREE_SENTENCES, TWO_SENTENCES, "moat phrase", "edge"])
    assert step_circle(state, ask) == "hell_no"     # hard 2-sentence limit: re-asked
    assert state["business_model_2s"] == TWO_SENTENCES


def test_circle_step_outside_is_pass():
    from agentcy.gate import step_circle
    state = {}
    ask = ScriptedAsker([TWO_SENTENCES, "moat phrase", "outside"])
    assert step_circle(state, ask) == "verdict"
    assert state["pending_pass"]["reason_class"] == "outside_circle"


def test_circle_step_cant_write_it_is_pass():
    from agentcy.gate import step_circle
    state = {}
    ask = ScriptedAsker(["   "])                     # blank = can't write it
    assert step_circle(state, ask) == "verdict"
    assert state["pending_pass"]["reason_class"] == "outside_circle"


# --- P4.3 hell-no step --------------------------------------------------------

def test_hell_no_all_pass():
    from agentcy.gate import step_hell_no
    state = {}
    ask = ScriptedAsker(["no"] * 5)
    assert step_hell_no(state, ask) == "dossier"
    assert state["hell_no"] == {"HN1": "no", "HN2": "no", "HN3": "no", "HN4": "no", "HN5": "no"}


def test_hell_no_one_fail_rejects_but_records_all_five():
    from agentcy.gate import step_hell_no
    state = {}
    # HN2 fails; HN3..HN5 must STILL be asked and recorded (C.3: "remaining tests
    # still recorded for the journal")
    ask = ScriptedAsker(["no", "yes", "no", "no", "yes"])
    assert step_hell_no(state, ask) == "verdict"
    assert state["pending_pass"]["reason_class"] == "hell_no_HN2"   # first failing test
    assert state["hell_no"]["HN5"] == "yes"                          # all five recorded
    assert len(ask.log) == 5


def test_hell_no_prompts_are_binary():
    from agentcy.gate import step_hell_no
    state = {}
    ask = ScriptedAsker(["no"] * 5)
    step_hell_no(state, ask)
    assert all(opts == ("yes", "no") for _, opts in ask.log)


# --- P4.4 dossier -------------------------------------------------------------

from agentcy.freshness import Stamped, DataState
from agentcy.fetch.store import OwnerEarnings


def _fresh(value, note=None):
    return Stamped(value=value, fetched_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
                   state=DataState.FRESH, note=note)


def _oe(**kw):
    base = dict(fcf_ttm=1.1e9, sbc_ttm=0.45e9, owner_fcf_ttm=0.65e9,
                owner_fcf_per_share_ttm=4.0, owner_fcf_margin_ttm=0.28,
                periods_used=("2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"))
    base.update(kw)
    return OwnerEarnings(**base)


class FakeStore:
    """Monkeypatch seam for the P2 store: only what the dossier + fair-band read."""
    def __init__(self, *, owner_earnings=None, denom=None, close=None,
                 income_periods=("2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30")):
        self._oe = owner_earnings
        self._denom = denom
        self._close = close
        self._income_periods = income_periods

    def owner_fcf_ttm(self, conn, yf_ticker, *, as_of):
        return self._oe

    def denominator_per_share(self, conn, yf_ticker, *, as_of):
        return self._denom

    def latest_close(self, conn, yf_ticker, *, as_of):
        return self._close

    def statement_history(self, conn, yf_ticker, statement_type, *, as_of):
        rows = [{"period_end": p} for p in self._income_periods]
        return _fresh(rows)


def test_dossier_happy_prints_period_counts_and_multiple(tmp_db, fixed_clock):
    from agentcy.gate import build_dossier
    from agentcy.fetch.store import PriceBar
    store = FakeStore(owner_earnings=_fresh(_oe()),
                      denom=_fresh(4.0),
                      close=_fresh(PriceBar(bar_date="2026-07-07", close=120.0,
                                            adj_close=120.0, dividend=0.0, currency="USD")))
    dossier = build_dossier(tmp_db, "VEEV", as_of=fixed_clock.now(), store=store)
    assert dossier["income_period_count"] == 4
    assert dossier["income_periods"][0] == "2026-03-31"
    assert dossier["owner_fcf_per_share_ttm"] == 4.0
    assert dossier["current_multiple"] == 30.0          # close 120 / owner-FCF/sh 4.0
    assert dossier["owner_fcf_ttm"] == 0.65e9


def test_dossier_pauses_on_absent_owner_earnings(tmp_db, fixed_clock):
    from agentcy.gate import build_dossier, DossierPaused
    store = FakeStore(owner_earnings=None)               # empty fundamentals
    with pytest.raises(DossierPaused):
        build_dossier(tmp_db, "VEEV", as_of=fixed_clock.now(), store=store)


def test_dossier_pauses_on_stale_owner_earnings(tmp_db, fixed_clock):
    from agentcy.gate import build_dossier, DossierPaused
    stale = Stamped(value=_oe(), fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    state=DataState.STALE)
    store = FakeStore(owner_earnings=stale)              # not usable()
    with pytest.raises(DossierPaused):
        build_dossier(tmp_db, "VEEV", as_of=fixed_clock.now(), store=store)


def test_dossier_multiple_none_when_price_absent(tmp_db, fixed_clock):
    from agentcy.gate import build_dossier
    store = FakeStore(owner_earnings=_fresh(_oe()), denom=_fresh(4.0), close=None)
    dossier = build_dossier(tmp_db, "VEEV", as_of=fixed_clock.now(), store=store)
    assert dossier["current_multiple"] is None          # dossier still assembles (BUF-12 backfill safe)


# --- P4.5 judgment step -------------------------------------------------------

TEN_YEAR = ("Yes. Life-sciences regulation only accumulates; the vendor that owns "
            "the validated record layer compounds with the industry.")

STATUS_Q = "Would you still buy this if you could never tell anyone you owned it?"


def _judgment_answers(*, conviction="high", mgmt="trusted_owner_operator",
                      circle="core", status="yes"):
    # order: conviction, mgmt_trust, mgmt_note, circle_fit, circle_note,
    #        ten_year_statement, status_answer, [status_buy_note if not "yes"]
    return [conviction, mgmt, "founder-CEO, large stake", circle,
            "healthcare SaaS", TEN_YEAR, status, "dinner-party temptation, honestly"]


def test_judgment_happy_no_status_flag():
    from agentcy.gate import step_judgment
    state = {"circle_fit_initial": "core"}
    ask = ScriptedAsker(_judgment_answers(status="yes"))
    assert step_judgment(state, ask) == "drafting"
    assert state["conviction"] == "high"
    assert state["mgmt_trust"] == "trusted_owner_operator"
    assert state["circle_fit"] == "core"
    assert state["ten_year_statement"] == TEN_YEAR
    assert state["status_buy_flag"] is False


def test_judgment_status_question_is_verbatim():
    from agentcy.gate import step_judgment
    state = {"circle_fit_initial": "core"}
    ask = ScriptedAsker(_judgment_answers())
    step_judgment(state, ask)
    prompts = [p for p, _ in ask.log]
    assert any(STATUS_Q in p for p in prompts)


def test_judgment_hesitant_status_sets_flag():
    from agentcy.gate import step_judgment
    state = {"circle_fit_initial": "core"}
    ask = ScriptedAsker(_judgment_answers(status="no"))
    step_judgment(state, ask)
    assert state["status_buy_flag"] is True


def test_judgment_conviction_reasked_until_in_set():
    from agentcy.gate import step_judgment
    state = {"circle_fit_initial": "core"}
    ask = ScriptedAsker(["huge", "high"] + _judgment_answers()[1:])
    assert step_judgment(state, ask) == "drafting"
    assert state["conviction"] == "high"        # 'huge' rejected, re-asked


def test_judgment_no_default_prompts_enumerate():
    from agentcy.gate import step_judgment
    state = {"circle_fit_initial": "core"}
    ask = ScriptedAsker(_judgment_answers())
    step_judgment(state, ask)
    conv_opts = next(opts for p, opts in ask.log if "conviction" in p.lower())
    assert conv_opts == ("high", "medium", "low")


# --- P4.6 drafting step -------------------------------------------------------

def _one_trigger(*, type="growth_floor", statement="rev YoY < 10% for 2q",
                 metric="revenue_yoy", comparator="<", threshold="10",
                 moat_link="", persistence="2_consecutive_quarters", yes_means=""):
    # order per _ask_trigger: type, statement, metric, comparator, threshold,
    #   moat_link, persistence, (yes_means only if type-5)
    seq = [type, statement, metric, comparator, threshold, moat_link, persistence]
    if type == "owner_attested_event":
        seq.append(yes_means)
    return seq


def _drafting_answers(triggers, *, moat_types="switching_costs", moat_evidence="retention >115%",
                      band_low="25", band_high="35", denom_note="P/owner-FCF"):
    seq = [moat_types, moat_evidence, band_low, band_high, denom_note, str(len(triggers))]
    for t in triggers:
        seq += t
    return seq


def test_drafting_happy_two_triggers_one_moat_linked():
    from agentcy.gate import step_drafting
    state = {}
    triggers = [
        _one_trigger(moat_link="switching_costs"),                 # moat-linked
        _one_trigger(type="dilution", statement="shares +3%/12m",
                     metric="shares_yoy", threshold="3", persistence="ttm"),
    ]
    ask = ScriptedAsker(_drafting_answers(triggers))
    assert step_drafting(state, ask) == "verdict"
    assert state["moat_types"] == ["switching_costs"]
    assert state["fair_band_low"] == 25.0
    assert state["fair_band_high"] == 35.0
    assert len(state["triggers"]) == 2
    assert state["triggers"][0]["moat_link"] == "switching_costs"


def test_drafting_rejects_count_below_2_and_above_5():
    from agentcy.gate import step_drafting
    state = {}
    t = _one_trigger(moat_link="switching_costs")
    # count answers: '1' rejected, '6' rejected, then '2' accepted
    ask = ScriptedAsker(
        ["switching_costs", "retention >115%", "25", "35", "P/owner-FCF",
         "1", "6", "2"] + t + t)
    assert step_drafting(state, ask) == "verdict"
    assert len(state["triggers"]) == 2


def test_drafting_requires_at_least_one_moat_link():
    from agentcy.gate import step_drafting
    state = {}
    # first pass: two triggers, neither moat-linked -> rejected, owner re-drafts
    # with a moat_link on the second attempt. Simulate by scripting a full re-ask.
    no_link = _one_trigger(moat_link="")
    linked = _one_trigger(moat_link="switching_costs")
    ask = ScriptedAsker(
        ["switching_costs", "retention >115%", "25", "35", "P/owner-FCF",
         "2"] + no_link + no_link +                         # first draft: no moat_link
        ["2"] + linked + no_link)                           # re-draft: one linked
    assert step_drafting(state, ask) == "verdict"
    assert any(t["moat_link"] for t in state["triggers"])


def test_drafting_type5_captures_yes_means():
    from agentcy.gate import step_drafting
    state = {}
    t5 = _one_trigger(type="owner_attested_event",
                      statement="Has the founder-CEO departed?",
                      metric="", comparator="", threshold="",
                      moat_link="switching_costs",
                      persistence="single_observation", yes_means="fire")
    growth = _one_trigger(moat_link="")
    ask = ScriptedAsker(_drafting_answers([t5, growth]))
    step_drafting(state, ask)
    t5row = next(t for t in state["triggers"] if t["type"] == "owner_attested_event")
    assert t5row["yes_means"] == "fire"
    assert t5row["check_method"] == "prompted"


# --- P4.7 verdict classification ---------------------------------------------

def test_classify_pass_from_pending():
    from agentcy.gate import classify_verdict
    state = {"pending_pass": {"reason_class": "hell_no_HN2", "note": "x"}}
    v = classify_verdict(tmp_db_unused=None, state=state, dossier=None, config_map={})
    assert v["verdict"] == "PASS"
    assert v["reason_class"] == "hell_no_HN2"


def _config_map():
    return {"initial_weight_high_pct": "10", "initial_weight_medium_pct": "6",
            "initial_weight_low_pct": "3", "buy_opportunity_discount_pct": "20",
            "position_count_high": "15"}


def test_classify_buy_ready_price_at_band_high():
    from agentcy.gate import classify_verdict
    state = {"conviction": "high", "fair_band_low": 25.0, "fair_band_high": 35.0,
             "circle_fit": "core", "status_buy_flag": False}
    dossier = {"current_multiple": 34.0}                 # at/below high -> BUY_READY
    v = classify_verdict(tmp_db_unused=None, state=state, dossier=dossier,
                         config_map=_config_map())
    assert v["verdict"] == "BUY_READY"
    assert v["suggested_max_weight_pct"] == 10.0         # high conviction


def test_classify_watch_price_above_band():
    from agentcy.gate import classify_verdict
    state = {"conviction": "medium", "fair_band_low": 25.0, "fair_band_high": 35.0,
             "circle_fit": "core", "status_buy_flag": False}
    dossier = {"current_multiple": 40.0}                 # above high -> WATCH
    v = classify_verdict(tmp_db_unused=None, state=state, dossier=dossier,
                         config_map=_config_map())
    assert v["verdict"] == "WATCH"
    assert v["suggested_max_weight_pct"] is None         # WATCH suggests no size


def test_classify_low_conviction_carries_standing_question():
    from agentcy.gate import classify_verdict
    state = {"conviction": "low", "fair_band_low": 25.0, "fair_band_high": 35.0,
             "circle_fit": "core", "status_buy_flag": False}
    dossier = {"current_multiple": 30.0}
    v = classify_verdict(tmp_db_unused=None, state=state, dossier=dossier,
                         config_map=_config_map())
    assert v["verdict"] == "BUY_READY"
    assert v["suggested_max_weight_pct"] == 3.0
    assert any("high-conviction" in q for q in v["standing_questions"])


def test_classify_edge_circle_fit_carries_standing_question():
    from agentcy.gate import classify_verdict
    state = {"conviction": "high", "fair_band_low": 25.0, "fair_band_high": 35.0,
             "circle_fit": "edge", "status_buy_flag": False}
    dossier = {"current_multiple": 30.0}
    v = classify_verdict(tmp_db_unused=None, state=state, dossier=dossier,
                         config_map=_config_map())
    assert any("high-conviction" in q for q in v["standing_questions"])


def test_classify_status_buy_requires_rebuttal_flag():
    from agentcy.gate import classify_verdict
    state = {"conviction": "high", "fair_band_low": 25.0, "fair_band_high": 35.0,
             "circle_fit": "core", "status_buy_flag": True}
    dossier = {"current_multiple": 30.0}
    v = classify_verdict(tmp_db_unused=None, state=state, dossier=dossier,
                         config_map=_config_map())
    assert v["requires_status_rebuttal"] is True
