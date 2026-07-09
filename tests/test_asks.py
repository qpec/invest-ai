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
