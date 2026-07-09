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
