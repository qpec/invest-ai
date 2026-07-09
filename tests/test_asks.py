"""tests/test_asks.py — D.5 ask state machine."""
import json
from datetime import datetime, timezone

import pytest

from agentcy import db


def test_mint_forms_id_and_persists_as_open(tmp_db, fixed_clock):
    from agentcy import asks
    ask = asks.mint(tmp_db, kind="Q", prompt="Has the founder departed?",
                    options=["yes", "no", "cant"], expects_freetext=True,
                    thesis_ref="TH-VEEV-001", trigger_ref=None, clock=fixed_clock)
    assert ask.ask_id == "Q1" and ask.status == "open"
    assert ask.options == ("yes", "no", "cant") and ask.expects_freetext is True
    again = asks.mint(tmp_db, kind="Q", prompt="p2", options=["yes", "no"], clock=fixed_clock)
    assert again.ask_id == "Q2"                       # monotonic per kind
    assert asks.mint(tmp_db, kind="A", prompt="p", options=[], clock=fixed_clock).ask_id == "A1"


def test_get_and_open_asks(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="R", prompt="new position?", options=["backfill", "outside"],
                  clock=fixed_clock)
    assert asks.get(tmp_db, "R1").ask_id == a.ask_id
    assert asks.get(tmp_db, "R999") is None
    assert [x.ask_id for x in asks.open_asks(tmp_db)] == ["R1"]
    assert [x.ask_id for x in asks.open_asks(tmp_db, kind="R")] == ["R1"]
    assert asks.open_asks(tmp_db, kind="A") == []


def test_mint_rejects_bad_kind(tmp_db, fixed_clock):
    from agentcy import asks
    with pytest.raises(ValueError, match="kind"):
        asks.mint(tmp_db, kind="Z", prompt="p", options=[], clock=fixed_clock)


def test_answer_valid_choice_records_and_routes(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="Q", prompt="p", options=["yes", "no", "cant"],
                  expects_freetext=True, clock=fixed_clock)
    out = asks.answer(tmp_db, a.ask_id, choice="yes", clock=fixed_clock)
    assert out.accepted and not out.already_recorded and out.consequence == "trigger.answer"
    assert asks.get(tmp_db, a.ask_id).status == "answered"
    assert asks.get(tmp_db, a.ask_id).answer == {"choice": "yes"}


def test_answer_cant_verify_routes_unverifiable(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="Q", prompt="p", options=["yes", "no", "cant"],
                  expects_freetext=True, clock=fixed_clock)
    out = asks.answer(tmp_db, a.ask_id, choice="cant", text="cannot see filings", clock=fixed_clock)
    assert out.consequence == "trigger.unverifiable"
    assert asks.get(tmp_db, a.ask_id).answer == {"choice": "cant", "text": "cannot see filings"}


def test_answer_out_of_set_rejected_no_state_change(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="R", prompt="p", options=["backfill", "outside"], clock=fixed_clock)
    out = asks.answer(tmp_db, a.ask_id, choice="banana", clock=fixed_clock)
    assert not out.accepted
    assert asks.get(tmp_db, a.ask_id).status == "open"    # unchanged


def test_answer_double_tap_idempotent(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="A", prompt="p", options=["confirm", "refute"], clock=fixed_clock)
    asks.answer(tmp_db, a.ask_id, choice="confirm", clock=fixed_clock)
    out2 = asks.answer(tmp_db, a.ask_id, choice="confirm", clock=fixed_clock)
    assert out2.already_recorded and out2.accepted        # "already recorded", harmless
    assert asks.get(tmp_db, a.ask_id).status == "answered"


def test_answer_records_tg_message_id(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="V", prompt="p", options=["reject", "watch"], clock=fixed_clock)
    asks.answer(tmp_db, a.ask_id, choice="watch", clock=fixed_clock, tg_message_id=555)
    assert db.fetch_ask(tmp_db, a.ask_id)["tg_message_id"] == 555


def test_reprompt_moves_open_to_reprompted_once(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="Q", prompt="p", options=["yes", "no"], clock=fixed_clock)
    r = asks.reprompt(tmp_db, a.ask_id, clock=fixed_clock)
    assert r.status == "reprompted"
    with pytest.raises(ValueError, match="reprompt"):
        asks.reprompt(tmp_db, a.ask_id, clock=fixed_clock)      # no second re-prompt


def test_reprompt_rejects_answered(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="Q", prompt="p", options=["yes", "no"], clock=fixed_clock)
    asks.answer(tmp_db, a.ask_id, choice="yes", clock=fixed_clock)
    with pytest.raises(ValueError):
        asks.reprompt(tmp_db, a.ask_id, clock=fixed_clock)


def test_sweep_marks_unanswered_after_effective_deadline(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="A", prompt="p", options=["confirm", "refute"],
                  deadline="2026-07-15T05:00:00Z", clock=fixed_clock)
    before = datetime(2026, 7, 14, tzinfo=timezone.utc)
    assert asks.sweep_deadlines(tmp_db, as_of=before) == []          # not yet due
    after = datetime(2026, 7, 16, tzinfo=timezone.utc)
    outcomes = asks.sweep_deadlines(tmp_db, as_of=after)
    assert [(o.ask.ask_id, o.consequence) for o in outcomes] == [("A1", "alert.ignored")]
    assert asks.get(tmp_db, "A1").status == "unanswered"


def test_sweep_is_pause_aware(tmp_db, fixed_clock):
    from agentcy import asks
    # a pause covering the deadline window freezes the counter
    db.append_absence_event(tmp_db, kind="on", at="2026-07-10T00:00:00Z", journal_ref=1)
    a = asks.mint(tmp_db, kind="Q", prompt="p", options=["yes", "no", "cant"],
                  expects_freetext=True, deadline="2026-07-15T05:00:00Z", clock=fixed_clock)
    after = datetime(2026, 7, 16, tzinfo=timezone.utc)
    assert asks.sweep_deadlines(tmp_db, as_of=after) == []            # frozen: open-ended pause
    assert asks.get(tmp_db, "Q1").status == "open"


def test_sweep_skips_asks_without_deadline(tmp_db, fixed_clock):
    from agentcy import asks
    asks.mint(tmp_db, kind="N", prompt="circle note?", options=[], expects_freetext=True,
              clock=fixed_clock)
    far = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert asks.sweep_deadlines(tmp_db, as_of=far) == []
    assert asks.get(tmp_db, "N1").status == "open"


def test_sweep_consequence_per_kind(tmp_db, fixed_clock):
    from agentcy import asks
    for k, cons in [("F", "reaff.skip"), ("V", "vfu.unanswered")]:
        a = asks.mint(tmp_db, kind=k, prompt="p", options=["a", "b"],
                      deadline="2026-07-15T05:00:00Z", clock=fixed_clock)
        out = asks.sweep_deadlines(tmp_db, as_of=datetime(2026, 7, 16, tzinfo=timezone.utc))
        assert any(o.ask.ask_id == a.ask_id and o.consequence == cons for o in out)


def test_resolve_freetext_reply_to_authoritative(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="A", prompt="refute?", options=["refute"], expects_freetext=True,
                  clock=fixed_clock)
    asks.mint(tmp_db, kind="Q", prompt="note?", options=["cant"], expects_freetext=True,
              clock=fixed_clock)
    got = asks.resolve_freetext(tmp_db, reply_to_ask_id=a.ask_id)
    assert isinstance(got, asks.Ask) and got.ask_id == a.ask_id


def test_resolve_freetext_exactly_one_open(tmp_db, fixed_clock):
    from agentcy import asks
    a = asks.mint(tmp_db, kind="A", prompt="refute?", options=["refute"], expects_freetext=True,
                  clock=fixed_clock)
    got = asks.resolve_freetext(tmp_db, reply_to_ask_id=None)
    assert isinstance(got, asks.Ask) and got.ask_id == a.ask_id


def test_resolve_freetext_several_open_returns_list(tmp_db, fixed_clock):
    from agentcy import asks
    a1 = asks.mint(tmp_db, kind="A", prompt="p", options=["refute"], expects_freetext=True,
                   clock=fixed_clock)
    a2 = asks.mint(tmp_db, kind="Q", prompt="p", options=["cant"], expects_freetext=True,
                   clock=fixed_clock)
    got = asks.resolve_freetext(tmp_db, reply_to_ask_id=None)
    assert isinstance(got, list) and {x.ask_id for x in got} == {a1.ask_id, a2.ask_id}


def test_resolve_freetext_none_when_no_open(tmp_db, fixed_clock):
    from agentcy import asks
    assert asks.resolve_freetext(tmp_db, reply_to_ask_id=None) is None
    # a stale reply-to to an already-answered ask also yields None (never stored)
    a = asks.mint(tmp_db, kind="A", prompt="p", options=["refute"], expects_freetext=True,
                  clock=fixed_clock)
    asks.answer(tmp_db, a.ask_id, text="evidence", clock=fixed_clock)
    assert asks.resolve_freetext(tmp_db, reply_to_ask_id=a.ask_id) is None
