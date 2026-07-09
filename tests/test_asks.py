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
