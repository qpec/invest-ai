"""Stage-2 QualitativeReviewer interface + DeskReviewer adapter + Verdict dataclass.
Minimal, no LLM: the DeskReviewer just surfaces already-recorded verdicts (design Part A)."""
import pytest
from agentcy import scout_review as sr


def test_verdict_defaults_all_axes_pending():
    v = sr.Verdict()
    assert v.moat is None and v.mgmt is None and v.fad is None and v.tier is None
    assert v.reason is None


def test_verdict_rejects_unknown_axis_values():
    with pytest.raises(ValueError):
        sr.Verdict(moat="maybe")
    with pytest.raises(ValueError):
        sr.Verdict(mgmt="great")
    with pytest.raises(ValueError):
        sr.Verdict(fad="trend")
    with pytest.raises(ValueError):
        sr.Verdict(tier="Core")            # tier correction must be 'ok' or 'correction:<T>'
    # a valid tier correction is accepted
    assert sr.Verdict(tier="correction:Adjacent").tier == "correction:Adjacent"


def test_desk_reviewer_returns_recorded_verdict_or_pending():
    recorded = {"MSFT": sr.Verdict(moat="confirmed", mgmt="aligned", fad="clear", tier="ok",
                                   reason="switching costs; founder-led; real trend")}
    rv = sr.DeskReviewer(recorded)
    assert isinstance(rv, sr.QualitativeReviewer)
    assert rv.review("MSFT").moat == "confirmed"
    # an unrecorded ticker is all-pending, never faked (FR9)
    assert rv.review("UNKN") == sr.Verdict()
