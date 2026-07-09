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


from datetime import datetime, timezone


def _entry(tmp_db, fixed_clock, **kw):
    from agentcy import journal
    base = dict(decision_type="buy", ticker="VEEV", thesis_ref="TH-VEEV-001@1",
                reasoning_at_the_moment="r", owner_action="followed", process="followed")
    base.update(kw)
    return journal.append(tmp_db, journal.EntryIn(**base), clock=fixed_clock)


def test_grade_appends_never_mutates(tmp_db, fixed_clock):
    from agentcy import journal
    eid = _entry(tmp_db, fixed_clock)
    journal.grade(tmp_db, eid, outcome_grade="good", note="thesis held", clock=fixed_clock)
    grades = db.fetch_grades_for(tmp_db, eid)
    assert [g["outcome_grade"] for g in grades] == ["good"]
    assert db.fetch_journal_entry(tmp_db, eid)["reasoning_at_the_moment"] == "r"  # untouched


def test_grade_rejects_bad_value(tmp_db, fixed_clock):
    from agentcy import journal
    eid = _entry(tmp_db, fixed_clock)
    with pytest.raises(ValueError):
        journal.grade(tmp_db, eid, outcome_grade="excellent", note=None, clock=fixed_clock)


def test_due_for_review_and_too_early_requeue(tmp_db, fixed_clock):
    from agentcy import journal
    eid = _entry(tmp_db, fixed_clock)   # horizon = 2027-07-08
    at_horizon = datetime(2027, 7, 9, tzinfo=timezone.utc)
    due = journal.due_for_review(tmp_db, as_of=at_horizon)
    assert [r["entry_id"] for r in due] == [eid]
    journal.grade(tmp_db, eid, outcome_grade="too_early", note=None, clock=fixed_clock)
    # too_early re-queues one horizon: due again 1y after grading, not before
    assert journal.due_for_review(tmp_db, as_of=at_horizon) == []
    later = datetime(2028, 7, 9, tzinfo=timezone.utc)
    assert [r["entry_id"] for r in journal.due_for_review(tmp_db, as_of=later)] == [eid]


def test_review_matrix_flags_dangerous_win(tmp_db, fixed_clock):
    from agentcy import journal
    e1 = _entry(tmp_db, fixed_clock)                                   # followed
    e2 = _entry(tmp_db, fixed_clock, process="deviated",
                process_deviation_note="bought above band", owner_action="overridden")
    journal.grade(tmp_db, e1, outcome_grade="good", note=None, clock=fixed_clock)
    journal.grade(tmp_db, e2, outcome_grade="good", note=None, clock=fixed_clock)
    journal.append(tmp_db, journal.EntryIn(decision_type="alert_ignored", ticker="CRWD",
                                           actor="system"), clock=fixed_clock)
    m = journal.review_matrix(tmp_db, ("2026-07-01T00:00:00Z", "2026-09-30T23:59:59Z"))
    assert m["matrix"][("followed", "good")] == [e1]
    assert m["dangerous_wins"] == [e2]                                  # deviated/good, loudest
    assert m["alert_ignored"] == 1
    assert m["followed_pct"] == 50.0 and m["overridden_pct"] == 50.0
    assert m["override_hit_rate"] == 100.0
    assert 0.0 <= m["no_action_ratio"] <= 1.0


def test_bootstrap_entry_id(tmp_db):
    from agentcy import journal
    assert db.fetch_journal_entry(tmp_db, journal.bootstrap_entry_id()) is not None
