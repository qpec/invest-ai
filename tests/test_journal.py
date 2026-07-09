"""tests/test_journal.py — F.1 Decision Journal."""
import pytest

from agentcy import db


def test_owner_initiated_requires_reasoning(tmp_db, fixed_clock):
    from agentcy import journal
    e = journal.EntryIn(decision_type="sell", ticker="CRWD", reasoning_at_the_moment=None)
    with pytest.raises(ValueError, match="reasoning"):
        journal.append(tmp_db, e, clock=fixed_clock)


def test_auto_types_need_no_reasoning(tmp_db, fixed_clock):
    from agentcy import journal
    e = journal.EntryIn(decision_type="alert_ignored", ticker="CRWD", actor="system")
    entry_id = journal.append(tmp_db, e, clock=fixed_clock)
    row = db.fetch_journal_entry(tmp_db, entry_id)
    assert row["decision_type"] == "alert_ignored" and row["actor"] == "system"


def test_deviated_requires_note(tmp_db, fixed_clock):
    from agentcy import journal
    e = journal.EntryIn(decision_type="buy", ticker="VEEV", reasoning_at_the_moment="fits circle",
                        process="deviated", process_deviation_note=None)
    with pytest.raises(ValueError, match="deviation"):
        journal.append(tmp_db, e, clock=fixed_clock)


def test_buy_defaults_falsifier_and_horizon(tmp_db, fixed_clock):
    from agentcy import journal
    e = journal.EntryIn(decision_type="buy", ticker="VEEV", thesis_ref="TH-VEEV-001@1",
                        reasoning_at_the_moment="thesis committed at the Gate")
    entry_id = journal.append(tmp_db, e, clock=fixed_clock)
    row = db.fetch_journal_entry(tmp_db, entry_id)
    # F5: the thesis IS the falsifier; horizon defaults to +1y
    assert row["expectation_and_falsifier"] == "TH-VEEV-001@1"
    assert row["review_horizon"] == "2027-07-08T05:00:00Z"


def test_unknown_decision_type_rejected(tmp_db, fixed_clock):
    from agentcy import journal
    with pytest.raises(ValueError, match="decision_type"):
        journal.append(tmp_db, journal.EntryIn(decision_type="yolo"), clock=fixed_clock)
