"""The Low-Cap Desk's agent seam: lane work orders out, lane-validated artifacts in.

Same contract philosophy as test_thesis_engine — the harness IS the runtime, so these
tests drive the seam the way the harness does. What they protect: the lane packet
carries the Forge and all four lenses unmerged, a Forged-out name cannot get a work
order OR pass record, scuttlebutt.md is a required artifact (Pillar 3 is not optional),
and everything the main desk's record refuses stays refused here.
"""
import json

import pytest

import deskwork
import lowcap
import lowcap_thesis
import thesis

from test_lowcap import lane_bundle


APPROVED = deskwork.APPROVED_MODELS["anthropic"][0]


@pytest.fixture(autouse=True)
def _fixed_model(monkeypatch):
    monkeypatch.setattr(deskwork, "observed_model", lambda transcript=None: APPROVED)


CARD = {"pct": 62, "band": "Mixed", "evidence": "partial", "score": 40,
        "available_max": 65, "why": {}}
INV = {"verdict": "Unknown", "verdict_meaning": "Said out loud, never read as safe",
       "failure_modes": [], "coverage": {"severe": 0, "caution": 0}}


def lane_result(verdict="Survivor", findings=None):
    return {
        "symbol": "LOW", "eligible": True, "eligibility": "in the band",
        "forge": {"verdict": verdict,
                  "verdict_meaning": lowcap.FORGE_VERDICTS[verdict]["meaning"],
                  "findings": findings or [],
                  "coverage": {"measured_count": 4, "total": 6, "thin": False,
                               "severe": 1 if verdict == "Forged-out" else 0,
                               "caution": 0, "measured": [], "required_missing": []}},
        "lenses": {name: {"lens": name, "verdict": "silent", "detail": "measured, no",
                          "checks": {}, "rank": None}
                   for name in lowcap.LENS_ORDER},
        "metrics": {"ncav": None, "peg": 0.8},
    }


def write_brief(tmp_path, lane=None):
    return lowcap_thesis.brief(
        "LOW", lane_bundle("LOW"), CARD, INV, lane or lane_result(),
        theses_dir=tmp_path, name="Low Corp", sector="Industrials",
        with_filings=False)


def metric_trigger(tid="T1", metric="owner_fcf_margin_pct", op="<", threshold=5.0):
    return {"id": tid, "kind": "metric", "action": "break",
            "statement": f"{metric} {op} {threshold}", "metric": metric, "op": op,
            "threshold": threshold, "consecutive_checks": 2, "question": None}


def question_trigger(tid, kind="narrative", action="review"):
    q = "Is there credible evidence the niche is being commoditized?"
    return {"id": tid, "kind": kind, "action": action, "statement": q, "metric": None,
            "op": None, "threshold": None, "consecutive_checks": None, "question": q}


def lane_draft():
    return {
        "symbol": "LOW",
        "business_model": "Sells niche industrial sensors. Replacement demand "
                          "funds the growth.",
        "moat": {"kind": "switching_costs", "evidence": ["qualified into OEM designs"]},
        "owner_earnings_picture": "Owner-FCF positive five years running.",
        "valuation_anchor": {"metric": "owner_fcf_yield_pct", "value": 9.0,
                             "statement": "9% owner-FCF yield at build"},
        "horizon_years": 10,
        "ten_year_statement": "We would hold this if the market closed for a decade.",
        "bear_case": "Illiquid; a large customer loss would take years to replace.",
        "triggers": [metric_trigger(), question_trigger("T2"),
                     question_trigger("T3", kind="event", action="break")],
        "sources": ["10-K"],
    }


def write_artifacts(tmp_path, *, scuttlebutt=True):
    out = tmp_path / "drafts" / "LOW"
    (out / "report.md").write_text("The research.", encoding="utf-8")
    (out / "summary.md").write_text(
        f"{thesis.SUMMARY_HEADING}\n\nAn illiquid small cap.", encoding="utf-8")
    if scuttlebutt:
        (out / "scuttlebutt.md").write_text(
            "1. Founder owns 22% (DEF 14A). … 5. No coverage; too small for indexes.",
            encoding="utf-8")
    deskwork.write_json(out / "thesis.json", lane_draft())


class TestBrief:
    def test_the_order_carries_forge_lenses_and_scuttlebutt(self, tmp_path):
        path = write_brief(tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "The Forge (survive first)" in text
        assert "voices, never votes" in text
        for lens in ("GRAHAM", "GARP", "DOWNSIDE", "COMPOUNDER"):
            assert lens in text
        assert "scuttlebutt.md" in text and "The scuttlebutt questions" in text
        assert "lowcap_thesis.py record LOW" in text
        # The main desk's grounding rides along, unmerged.
        assert "The Owner's Scorecard" in text and "The Inversion Layer" in text

    def test_the_packet_records_the_lane(self, tmp_path):
        write_brief(tmp_path)
        packet = json.loads(
            (tmp_path / "drafts" / "LOW" / "packet.json").read_text(encoding="utf-8"))
        assert packet["lane"] == "lowcap"
        assert packet["lowcap"]["forge"]["verdict"] == "Survivor"
        assert set(packet["lowcap"]["lenses"]) == set(lowcap.LENS_ORDER)
        assert packet["metrics"]["owner_fcf_margin_pct"] is not None

    def test_a_forged_out_name_never_gets_an_order(self, tmp_path):
        lane = lane_result("Forged-out", findings=["Serial diluter — issued +14%/yr."])
        with pytest.raises(deskwork.OrderError, match="Forged-out"):
            write_brief(tmp_path, lane)
        assert not (tmp_path / "drafts" / "LOW").exists()


class TestRecord:
    def test_a_complete_lane_draft_is_accepted_and_marked(self, tmp_path):
        write_brief(tmp_path)
        write_artifacts(tmp_path)
        doc = lowcap_thesis.record("LOW", theses_dir=tmp_path)
        assert doc["lane"] == "lowcap"
        on_disk = json.loads(
            (tmp_path / "drafts" / "LOW" / "record.json").read_text(encoding="utf-8"))
        assert on_disk["lane"] == "lowcap" and on_disk["validation_problems"] == []

    def test_missing_scuttlebutt_is_a_refusal(self, tmp_path):
        write_brief(tmp_path)
        write_artifacts(tmp_path, scuttlebutt=False)
        with pytest.raises(deskwork.OrderError, match="scuttlebutt"):
            lowcap_thesis.record("LOW", theses_dir=tmp_path)

    def test_a_forged_out_packet_is_refused_even_with_perfect_artifacts(self, tmp_path):
        write_brief(tmp_path)
        write_artifacts(tmp_path)
        packet_path = tmp_path / "drafts" / "LOW" / "packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["lowcap"]["forge"]["verdict"] = "Forged-out"
        deskwork.write_json(packet_path, packet)
        with pytest.raises(deskwork.OrderError, match="Forged-out"):
            lowcap_thesis.record("LOW", theses_dir=tmp_path)

    def test_the_main_desk_contract_still_binds(self, tmp_path):
        """The lane never weakens the main contract: a draft with too few triggers is
        refused here exactly as thesis.record refuses it."""
        write_brief(tmp_path)
        write_artifacts(tmp_path)
        out = tmp_path / "drafts" / "LOW"
        bad = lane_draft()
        bad["triggers"] = [metric_trigger()]
        deskwork.write_json(out / "thesis.json", bad)
        with pytest.raises(deskwork.OrderError, match="minimum"):
            lowcap_thesis.record("LOW", theses_dir=tmp_path)


class TestLaneRows:
    def test_out_of_band_rows_never_become_candidates(self):
        big = lane_bundle("BIG")
        big["market_cap"] = 50e9
        rows = [{"symbol": "BIG", "bundle": big, "name": "Big", "sector": "IT",
                 "card": dict(CARD), "inversion": dict(INV)},
                {"symbol": "LOW", "bundle": lane_bundle("LOW"), "name": "Low",
                 "sector": "IT", "card": dict(CARD), "inversion": dict(INV)}]
        lane_rows = lowcap_thesis._lane_rows(rows, prices=None)
        assert [r["symbol"] for r in lane_rows] == ["LOW"]
        assert lane_rows[0]["lowcap"]["forge"]["verdict"] in lowcap.FORGE_VERDICTS
