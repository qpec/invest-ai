"""The thesis engine: work orders out, validated artifacts in.

There is no API client to fake — the agent harness IS the runtime, so these tests drive
the seam the way the harness does: write a work order, drop artifacts on disk as an agent
would, then assert what `record` and the monitor accept and refuse.

What they protect is the contract the design states out loud: an unvalidatable trigger
cannot reach the Gate, the agent cannot invent conviction, judgement never fires the sell
rule alone, an unanswered question reads as UNCHECKED rather than intact, and a broken
thesis stays broken until the owner acts.
"""
import json

import pytest

import deskwork
import monitor
import scoring
import thesis


APPROVED = deskwork.APPROVED_MODELS["anthropic"][0]


@pytest.fixture(autouse=True)
def _fixed_model(monkeypatch):
    """Pin the observed model for every test.

    Without this the suite reads whatever harness happens to be running it: green on the
    desk, red in CI, and silently dependent on ambient state — the exact class of test
    this repo refuses elsewhere. Tests that are ABOUT the gate override it explicitly."""
    monkeypatch.setattr(deskwork, "observed_model", lambda transcript=None: APPROVED)


def agent_block(model=None, provenance="observed"):
    model = APPROVED if model is None else model
    return {"id": model, "provider": deskwork.provider_of(model),
            "provenance": provenance,
            "approved": model in deskwork.approved_ids()}


# --- Fixture thesis material --------------------------------------------------------------

def metric_trigger(tid="T1", metric="owner_fcf_margin_pct", op="<", threshold=12.0,
                   action="break", checks=2):
    return {"id": tid, "kind": "metric", "action": action,
            "statement": f"{metric} {op} {threshold}",
            "metric": metric, "op": op, "threshold": threshold,
            "consecutive_checks": checks, "question": None}


def question_trigger(tid="T2", kind="narrative", action="review",
                     question="Is there credible evidence of structural decline?"):
    return {"id": tid, "kind": kind, "action": action, "statement": question,
            "metric": None, "op": None, "threshold": None,
            "consecutive_checks": None, "question": question}


def draft(symbol="AAA", triggers=None):
    return {
        "symbol": symbol,
        "business_model": "Sells widgets to enterprises. Renewals fund the growth.",
        "moat": {"kind": "switching_costs", "evidence": ["10-year contracts"]},
        "owner_earnings_picture": "Owner-FCF positive nine years running.",
        "valuation_anchor": {"metric": "owner_fcf_yield_pct", "value": 7.5,
                             "statement": "7.5% owner-FCF yield on own EV at build"},
        "horizon_years": 10,
        "ten_year_statement": "We would hold this if the market closed for a decade.",
        "bear_case": "The price has fallen 70% before and can again.",
        "triggers": triggers if triggers is not None else [
            metric_trigger(), question_trigger(),
            question_trigger("T3", kind="event", action="break",
                             question="Has the CEO departed?")],
        "sources": ["10-K"],
    }


def committed_doc(symbol="AAA", triggers=None):
    return {"symbol": symbol, "status": "committed", "version": 1,
            "conviction": "high", "circle_of_competence": "cloud",
            "thesis": draft(symbol, triggers), "trigger_state": {}}


# --- thesis.validate ----------------------------------------------------------------------

class TestValidate:
    def test_a_complete_draft_validates(self):
        assert thesis.validate(draft(), symbol="AAA") == []

    def test_an_unknown_metric_is_refused(self):
        bad = draft(triggers=[metric_trigger(metric="stock_price"),
                              question_trigger(), question_trigger("T3")])
        problems = thesis.validate(bad)
        assert any("not in the registry" in p for p in problems)

    def test_the_builder_may_not_invent_conviction(self):
        """FR9: conviction and circle fit are the owner's. A draft carrying either is
        rejected outright."""
        doc = draft()
        doc["conviction"] = "high"
        assert any("owner-only" in p for p in thesis.validate(doc))

    def test_a_narrative_trigger_may_only_review(self):
        bad = draft(triggers=[metric_trigger(), question_trigger(action="break"),
                              question_trigger("T3")])
        assert any("only send to review" in p for p in thesis.validate(bad))

    def test_at_least_one_metric_trigger_is_demanded(self):
        bad = draft(triggers=[question_trigger(), question_trigger("T3"),
                              question_trigger("T4")])
        assert any("no metric trigger" in p for p in thesis.validate(bad))

    def test_too_few_triggers_is_refused(self):
        assert any("minimum" in p
                   for p in thesis.validate(draft(triggers=[metric_trigger()])))

    def test_every_registry_metric_resolves_against_evaluate(self):
        """The registry's whole promise is that the monitor reads the same numbers the
        grader computes — every entry must map to a real scoring.evaluate key."""
        evaluated = {key: 1.0 for key, _, _ in thesis.METRICS.values()}
        for name in thesis.METRICS:
            assert thesis.metric_value(name, {}, evaluated) is not None

    def test_the_registry_carries_no_price_metric(self):
        for name in thesis.METRICS:
            assert "price" not in name and "drawdown" not in name

    def test_a_quote_derived_metric_cannot_fire_a_trigger(self):
        """2026-08-08 review V-8: owner-FCF yield embeds the market cap, so a price move
        alone could trip it — it stays in packets/display but is refused as a trigger."""
        bad = draft(triggers=[metric_trigger(metric="owner_fcf_yield_pct"),
                              metric_trigger("T1b"), question_trigger()])
        assert any("quote-derived" in p for p in thesis.validate(bad))

    def test_a_named_moat_without_evidence_is_refused(self):
        """Pillar 1: 'at least one durable competitive advantage, WITH EVIDENCE.'"""
        doc = draft()
        doc["moat"] = {"kind": "switching_costs", "evidence": []}
        assert any("no evidence" in p for p in thesis.validate(doc))
        doc["moat"] = {"kind": "brand_trust", "evidence": ["  "]}
        assert any("no evidence" in p for p in thesis.validate(doc))

    def test_an_honest_no_moat_finding_still_validates(self):
        """kind 'none' is a finding, not a formatting error — record accepts it as
        research and marks it PASS-RECOMMENDED; the refusal happens at ratify."""
        doc = draft()
        doc["moat"] = {"kind": "none", "evidence": []}
        assert thesis.validate(doc, symbol="AAA") == []

    @pytest.mark.parametrize("moat", [
        None,                                        # the key omitted entirely
        {},                                          # present but empty
        {"kind": "", "evidence": []},                # blank kind
        {"kind": "moat-ish", "evidence": ["x"]},     # off-enum kind
        "switching costs",                           # a string, not an object
        ["switching costs"],                         # a list
        {"kind": "brand_trust", "evidence": "text"}, # evidence not a list
    ])
    def test_a_malformed_moat_is_refused_not_waved_through_or_crashed(self, moat):
        """The schema is prose in the work order, not a validator, so validate() holds
        the shape. Before this check an omitted moat passed with zero problems (skipping
        the Pillar-1 door entirely) and a string moat raised AttributeError instead of
        producing a refusal."""
        doc = draft()
        if moat is None:
            doc.pop("moat")
        else:
            doc["moat"] = moat
        problems = thesis.validate(doc, symbol="AAA")      # must not raise
        assert problems and any("moat" in p for p in problems)

    def test_a_moatless_draft_cannot_reach_the_gate_by_omission(self, tmp_path):
        """The omission path all the way through: no moat key -> record refuses."""
        out = tmp_path / "drafts" / "AAA"
        out.mkdir(parents=True)
        doc = draft()
        doc.pop("moat")
        (out / "thesis.json").write_text(json.dumps(doc))
        for name in ("report.md", "summary.md"):
            (out / name).write_text(f"{thesis.SUMMARY_HEADING}\nbody")
        with pytest.raises(deskwork.OrderError, match="moat"):
            thesis.record("AAA", theses_dir=tmp_path, model=APPROVED)


# --- thesis.ratify (the Gate) -------------------------------------------------------------

class TestRatify:
    def _write_draft(self, tmp_path, doc):
        """An ACCEPTED draft — ratify reads record.json, which only `record` writes."""
        out = tmp_path / "drafts" / doc["thesis"]["symbol"]
        out.mkdir(parents=True, exist_ok=True)
        doc.setdefault("agent", agent_block())
        (out / "record.json").write_text(json.dumps(doc))

    def test_ratification_asks_the_owner_and_commits(self, tmp_path):
        self._write_draft(tmp_path, {"symbol": "AAA", "status": "draft",
                                     "thesis": draft()})
        answers = iter(["high", "cloud infrastructure is my day job"])
        doc = thesis.ratify("AAA", theses_dir=tmp_path, ask=lambda _: next(answers))
        assert doc["status"] == "committed" and doc["conviction"] == "high"
        assert (tmp_path / "committed" / "AAA.json").exists()

    def test_outside_the_circle_is_a_pass(self, tmp_path):
        """The framework wins: an empty circle answer refuses the commit."""
        self._write_draft(tmp_path, {"symbol": "AAA", "status": "draft",
                                     "thesis": draft()})
        answers = iter(["high", ""])
        with pytest.raises(ValueError, match="circle of competence"):
            thesis.ratify("AAA", theses_dir=tmp_path, ask=lambda _: next(answers))

    def test_a_no_moat_draft_is_a_pass_without_an_explicit_override(self, tmp_path):
        """Pillar 1's consequence at the last door: moat kind 'none' refuses the commit
        unless the owner types the override — the goalpost guard's 're-arm' shape."""
        doc = draft()
        doc["moat"] = {"kind": "none", "evidence": []}
        self._write_draft(tmp_path, {"symbol": "AAA", "status": "draft", "thesis": doc})
        answers = iter([""])                       # decline the override
        with pytest.raises(ValueError, match="no durable moat"):
            thesis.ratify("AAA", theses_dir=tmp_path, ask=lambda _: next(answers))
        assert not (tmp_path / "committed" / "AAA.json").exists()

    def test_a_no_moat_override_is_deliberate_and_typed(self, tmp_path):
        doc = draft()
        doc["moat"] = {"kind": "none", "evidence": []}
        self._write_draft(tmp_path, {"symbol": "AAA", "status": "draft", "thesis": doc})
        answers = iter(["override", "low", "my day job"])
        committed = thesis.ratify("AAA", theses_dir=tmp_path,
                                  ask=lambda _: next(answers))
        assert committed["status"] == "committed"

    def test_re_ratifying_a_broken_thesis_demands_an_explicit_re_arm(self, tmp_path):
        """A broken thesis is standing sell advice. Silently overwriting it — which the
        naive write did — is the sunk-cost trap operating itself."""
        committed = tmp_path / "committed"
        committed.mkdir(parents=True)
        old = committed_doc()
        old["status"] = "broken"
        (committed / "AAA.json").write_text(json.dumps(old))
        self._write_draft(tmp_path, {"symbol": "AAA", "status": "draft",
                                     "thesis": draft()})
        answers = iter(["high", "cloud", "no"])
        with pytest.raises(ValueError, match="re-ratification declined"):
            thesis.ratify("AAA", theses_dir=tmp_path, ask=lambda _: next(answers))
        assert json.loads((committed / "AAA.json").read_text())["status"] == "broken"

    def test_re_ratification_versions_archives_and_keeps_earned_streaks(self, tmp_path):
        committed = tmp_path / "committed"
        committed.mkdir(parents=True)
        old = committed_doc()
        old["trigger_state"] = {"T1": {"streak": 1}, "T2": {"last_checked": "w1"}}
        (committed / "AAA.json").write_text(json.dumps(old))
        # T1 unchanged (streak carries); T2's question is rewritten (streak does not).
        rewritten = draft(triggers=[metric_trigger(),
                                    question_trigger(question="A different question?"),
                                    question_trigger("T3", kind="event", action="break",
                                                     question="Has the CEO departed?")])
        self._write_draft(tmp_path, {"symbol": "AAA", "status": "draft",
                                     "thesis": rewritten})
        answers = iter(["high", "cloud"])
        doc = thesis.ratify("AAA", theses_dir=tmp_path, ask=lambda _: next(answers))
        assert doc["version"] == 2
        assert (committed / "history" / "AAA.v1.json").exists()
        assert doc["trigger_state"] == {"T1": {"streak": 1}}

    def test_a_loosened_threshold_is_announced(self, tmp_path, capsys):
        """The goalpost guard: rewriting the rule you were about to fail is how a thesis
        becomes unfalsifiable. It must be said out loud at ratification."""
        committed = tmp_path / "committed"
        committed.mkdir(parents=True)
        (committed / "AAA.json").write_text(json.dumps(committed_doc()))
        loose = draft(triggers=[metric_trigger(threshold=2.0),  # was 12.0, "<" -> easier
                                question_trigger(),
                                question_trigger("T3", kind="event", action="break",
                                                 question="Has the CEO departed?")])
        self._write_draft(tmp_path, {"symbol": "AAA", "status": "draft", "thesis": loose})
        answers = iter(["high", "cloud"])
        thesis.ratify("AAA", theses_dir=tmp_path, ask=lambda _: next(answers))
        assert "GOALPOST WARNING" in capsys.readouterr().out

    def test_a_trigger_without_an_id_is_refused(self):
        """The monitor keys evidence by trigger id; an empty id lets two triggers share
        one streak entry."""
        bad = draft(triggers=[dict(metric_trigger(), id=""), question_trigger(),
                              question_trigger("T3")])
        assert any("no id" in p for p in thesis.validate(bad))

    def test_an_unvalidatable_draft_cannot_be_ratified(self, tmp_path):
        bad = draft(triggers=[metric_trigger(metric="vibes"), question_trigger(),
                              question_trigger("T3")])
        self._write_draft(tmp_path, {"symbol": "AAA", "status": "draft", "thesis": bad})
        with pytest.raises(ValueError, match="not ratifiable"):
            thesis.ratify("AAA", theses_dir=tmp_path, ask=lambda _: "high")


# --- thesis.build -------------------------------------------------------------------------

class TestBriefAndRecord:
    def _row(self, monkeypatch):
        monkeypatch.setattr(thesis.scoring, "evaluate",
                            lambda bundle: {key: 10.0 for key, _, _
                                            in thesis.METRICS.values()})
        card = {"score": 70.0, "available_max": 87, "pct": 80, "band": "Exceptional",
                "evidence": "full", "why": {}}
        inv = {"verdict": "Ordinary", "verdict_meaning": "Normal business risk",
               "failure_modes": ["the price fell 45%"], "coverage": {"severe": 0}}
        return {"symbol": "AAA"}, card, inv

    def _agent_writes(self, tmp_path, symbol="AAA", doc=None, summary=None, report=None):
        """Stand in for the agent: drop the three artifacts on disk."""
        out = tmp_path / "drafts" / symbol
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.md").write_text(report or "# Report\nlong analysis")
        (out / "summary.md").write_text(
            summary if summary is not None
            else f"{thesis.SUMMARY_HEADING}\nplain words for a human")
        (out / "thesis.json").write_text(json.dumps(doc or draft(symbol)))
        return out

    def test_the_work_order_carries_everything_the_agent_needs(self, tmp_path,
                                                               monkeypatch):
        bundle, card, inv = self._row(monkeypatch)
        path = thesis.brief("AAA", bundle, card, inv, theses_dir=tmp_path,
                            name="Alpha Corp.", sector="IT", with_filings=False)
        text = path.read_text()
        assert path.name == deskwork.ORDER_NAME
        for needed in ("report.md", "summary.md", "thesis.json",     # the artifacts
                       "Constitution", "Trigger discipline",          # the rules
                       "owner_fcf_margin_pct",                        # the registry
                       "thesis.py record AAA"):                       # how it is judged
            assert needed in text, needed
        packet = json.loads((tmp_path / "drafts" / "AAA" / "packet.json").read_text())
        assert packet["metrics"]["owner_fcf_margin_pct"] == 10.0

    def test_a_good_artifact_set_is_accepted(self, tmp_path, monkeypatch):
        bundle, card, inv = self._row(monkeypatch)
        thesis.brief("AAA", bundle, card, inv, theses_dir=tmp_path, with_filings=False)
        self._agent_writes(tmp_path)
        doc = thesis.record("AAA", theses_dir=tmp_path)
        assert doc["status"] == "draft" and doc["validation_problems"] == []
        assert (tmp_path / "drafts" / "AAA" / "record.json").exists()

    def test_an_unvalidatable_trigger_is_refused_at_record(self, tmp_path, monkeypatch):
        """The agent is trusted for prose, never for the contract."""
        bundle, card, inv = self._row(monkeypatch)
        thesis.brief("AAA", bundle, card, inv, theses_dir=tmp_path, with_filings=False)
        bad = draft(triggers=[metric_trigger(metric="vibes"), question_trigger(),
                              question_trigger("T3")])
        self._agent_writes(tmp_path, doc=bad)
        with pytest.raises(deskwork.OrderError, match="not in the registry"):
            thesis.record("AAA", theses_dir=tmp_path)
        assert not (tmp_path / "drafts" / "AAA" / "record.json").read_text() == ""

    def test_a_missing_report_is_a_refusal_not_a_warning(self, tmp_path, monkeypatch):
        bundle, card, inv = self._row(monkeypatch)
        thesis.brief("AAA", bundle, card, inv, theses_dir=tmp_path, with_filings=False)
        out = self._agent_writes(tmp_path)
        (out / "report.md").unlink()
        with pytest.raises(deskwork.OrderError, match="report.md was not written"):
            thesis.record("AAA", theses_dir=tmp_path)

    def test_a_summary_without_its_heading_is_refused(self, tmp_path, monkeypatch):
        bundle, card, inv = self._row(monkeypatch)
        thesis.brief("AAA", bundle, card, inv, theses_dir=tmp_path, with_filings=False)
        self._agent_writes(tmp_path, summary="just some prose, no heading")
        with pytest.raises(deskwork.OrderError, match="required heading"):
            thesis.record("AAA", theses_dir=tmp_path)

    def test_a_trigger_on_an_uncomputable_metric_is_caught_at_record(self, tmp_path,
                                                                     monkeypatch):
        """Better to refuse now than to report it UNCHECKED every week forever."""
        monkeypatch.setattr(thesis.scoring, "evaluate", lambda bundle: {})
        card = {"score": 1.0, "available_max": 2, "pct": 50, "band": "Mixed",
                "evidence": "thin", "why": {}}
        inv = {"verdict": "Unknown", "failure_modes": [], "coverage": {"severe": 0}}
        thesis.brief("AAA", {"symbol": "AAA"}, card, inv, theses_dir=tmp_path,
                     with_filings=False)
        self._agent_writes(tmp_path)
        with pytest.raises(deskwork.OrderError, match="never check it"):
            thesis.record("AAA", theses_dir=tmp_path)

    def test_a_malformed_thesis_json_is_a_clean_refusal(self, tmp_path, monkeypatch):
        bundle, card, inv = self._row(monkeypatch)
        thesis.brief("AAA", bundle, card, inv, theses_dir=tmp_path, with_filings=False)
        out = self._agent_writes(tmp_path)
        (out / "thesis.json").write_text("{ not json")
        with pytest.raises(deskwork.OrderError, match="not valid JSON"):
            thesis.record("AAA", theses_dir=tmp_path)

    def test_ratify_cannot_be_reached_around_record(self, tmp_path, monkeypatch):
        """The Gate reads record.json, so an agent that skipped validation cannot commit
        a thesis by writing thesis.json alone."""
        bundle, card, inv = self._row(monkeypatch)
        thesis.brief("AAA", bundle, card, inv, theses_dir=tmp_path, with_filings=False)
        self._agent_writes(tmp_path)
        with pytest.raises(FileNotFoundError, match="no accepted draft"):
            thesis.ratify("AAA", theses_dir=tmp_path, ask=lambda _: "high")

    def test_the_packet_carries_both_judgements_unmerged(self, monkeypatch):
        bundle, card, inv = self._row(monkeypatch)
        inv["coverage"]["severe"] = 2
        body = thesis.packet(bundle, card, inv)
        assert "Scorecard" in body and "Inversion" in body
        assert "bear case MUST address each" in body

    def test_top_symbols_is_one_percent_by_the_scorecard_rules(self):
        rows = [{"symbol": f"S{i:03}", "card": {"pct": 50 + (i % 40), "band": "Strong",
                                                "evidence": "full", "score": 1,
                                                "available_max": 2}}
                for i in range(200)]
        rows.append({"symbol": "VET", "card": {"pct": None, "band": "VETOED"}})
        top = thesis.top_symbols(rows, len(rows))
        assert len(top) == 3                      # ceil(201 * 0.01)
        assert all(r["card"]["pct"] is not None for r in top)

    def test_top_symbols_applies_the_desk_eligibility_floor(self):
        """V-6: a microcap or penny name stays scored and visible on the site, but does
        not consume a desk work order. A row carrying no figure is never excluded."""
        card = {"pct": 90, "band": "Exceptional", "evidence": "full",
                "score": 90, "available_max": 100}
        rows = [
            {"symbol": "BIG", "card": dict(card), "market_cap": 5e9, "price": 100.0},
            {"symbol": "TINY", "card": dict(card, pct=99),
             "market_cap": thesis.DESK_MIN_MARKET_CAP - 1, "price": 100.0},
            {"symbol": "PENNY", "card": dict(card, pct=99), "market_cap": 5e9,
             "price": thesis.DESK_MIN_PRICE - 0.01},
            {"symbol": "NODATA", "card": dict(card, pct=80)},
            {"symbol": "BUNDLED", "card": dict(card, pct=99),
             "bundle": {"market_cap": thesis.DESK_MIN_MARKET_CAP - 1}},
        ]
        top = thesis.top_symbols(rows, 400)       # ceil(400 * 0.01) = 4 slots
        symbols = [r["symbol"] for r in top]
        assert "TINY" not in symbols and "PENNY" not in symbols
        assert "BUNDLED" not in symbols
        assert "BIG" in symbols and "NODATA" in symbols

    def test_the_floor_reads_the_bundle_shape_the_cli_actually_builds(self):
        """_load_rows carries price only INSIDE the bundle, so a bundle-only fallback
        for market cap but not price made `thesis.py batch` and the site compute
        different top-1% sets: a $3 stock got a work order the site then hid."""
        card = {"pct": 90, "band": "Exceptional", "evidence": "full",
                "score": 90, "available_max": 100}
        cli_row = {"symbol": "PENNY", "card": card,
                   "bundle": {"market_cap": 5e9, "price": 3.00}}
        assert thesis._clears_desk_floor(cli_row) is False
        ok_row = {"symbol": "BIG", "card": card,
                  "bundle": {"market_cap": 5e9, "price": 50.0}}
        assert thesis._clears_desk_floor(ok_row) is True


# --- monitor ------------------------------------------------------------------------------

class TestMetricTriggers:
    def test_persistence_is_demanded_before_a_break(self, monkeypatch):
        """consecutive_checks=2: the first hit is a streak of 1 (no break), the second
        fires. One noisy week cannot fire a rule that asked for two."""
        doc = committed_doc(triggers=[metric_trigger(checks=2)])
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 8.0})
        first = monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="2026-08-08")
        assert first["status"] == "intact" and doc["trigger_state"]["T1"]["streak"] == 1
        second = monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="2026-08-15")
        assert second["status"] == "broken" and second["broken_by"] == ["T1"]

    def test_recovery_resets_the_streak(self, monkeypatch):
        doc = committed_doc(triggers=[metric_trigger(checks=2)])
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 8.0})
        monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="w1")
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 20.0})
        result = monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="w2")
        assert result["status"] == "intact"
        assert doc["trigger_state"]["T1"]["streak"] == 0

    def test_broken_is_sticky_until_the_owner_acts(self, monkeypatch):
        """Once the pre-committed sell rule has fired, a metric drifting back over its
        line does not un-fire it — that would be the sunk-cost trap self-operating. Only
        the desk resurrects a thesis."""
        doc = committed_doc(triggers=[metric_trigger(checks=1)])
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 8.0})
        assert monitor.check_thesis(doc, bundle={"symbol": "AAA"},
                                    as_of="w1")["status"] == "broken"
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 30.0})
        result = monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="w2")
        assert result["status"] == "broken"
        assert doc["status"] == "broken"

    def test_a_same_day_rerun_does_not_double_count_the_streak(self, monkeypatch):
        """A manual re-run, a systemd retry, or crash recovery re-reads the SAME filings.
        Counting that as a second consecutive check would let one week satisfy a rule
        that pre-committed to two."""
        doc = committed_doc(triggers=[metric_trigger(checks=2)])
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 8.0})
        first = monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="2026-08-08")
        second = monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="2026-08-08")
        assert first["status"] == "intact" and second["status"] == "intact"
        assert doc["trigger_state"]["T1"]["streak"] == 1
        # A genuinely new week still advances it.
        third = monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="2026-08-15")
        assert third["status"] == "broken"

    def test_a_same_day_rerun_that_now_misses_still_resets(self, monkeypatch):
        """Idempotence must not freeze a streak: a miss is new information whenever it
        arrives."""
        doc = committed_doc(triggers=[metric_trigger(checks=2)])
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 8.0})
        monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="w1")
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 30.0})
        monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="w1")
        assert doc["trigger_state"]["T1"]["streak"] == 0

    def test_a_missing_revenue_denominator_is_unchecked_not_a_zero_margin(self):
        """scoring returned 0.0 for owner-FCF margin when revenue was missing. Against a
        pre-committed '< 12%' break trigger that sentinel reads as the WORST possible
        margin and fires the sell rule on a data gap. It must be None -> UNCHECKED."""
        bundle = {"symbol": "AAA", "annual": {"cashflow": {"2025-12-31": {
            "Operating Cash Flow": 100.0, "Capital Expenditure": -10.0}}}}
        assert scoring.evaluate(bundle)["ofcf_margin"] is None
        doc = committed_doc(triggers=[metric_trigger(checks=1)])
        result = monitor.check_thesis(doc, bundle=bundle, as_of="w1")
        assert result["status"] == "intact" and result["unchecked"] == ["T1"]
        assert doc["trigger_state"].get("T1", {}).get("streak") in (None, 0)

    def test_an_uncomputable_metric_is_unchecked_never_safe(self, monkeypatch):
        doc = committed_doc(triggers=[metric_trigger()])
        monkeypatch.setattr(monitor.scoring, "evaluate", lambda bundle: {})
        result = monitor.check_thesis(doc, bundle={"symbol": "AAA"}, as_of="w1")
        assert result["unchecked"] == ["T1"]
        assert "never read as safety" in result["triggers"][0]["detail"]


class TestQuestionTriggers:
    def _verdict(self, tripped, confidence, tid="T2"):
        return {tid: {"trigger_id": tid, "symbol": "AAA", "tripped": tripped,
                      "confidence": confidence, "evidence": "the filing says so",
                      "sources": ["sec.gov"]}}

    def test_no_verdict_means_unchecked_loudly(self):
        """The agent did not answer — that is a gap in the owner's monitoring, and it
        must never read as an intact thesis."""
        doc = committed_doc(triggers=[question_trigger()])
        result = monitor.check_thesis(doc, bundle=None, as_of="w1")
        assert result["status"] == "intact" and result["unchecked"] == ["T2"]
        assert "UNCHECKED" in result["triggers"][0]["detail"]
        assert "not an all-clear" in result["triggers"][0]["detail"]

    def test_a_tripped_narrative_reviews_and_never_breaks(self):
        doc = committed_doc(triggers=[question_trigger(action="review")])
        result = monitor.check_thesis(doc, bundle=None,
                                      verdicts=self._verdict(True, "high"), as_of="w1")
        assert result["status"] == "under_review"
        assert result["broken_by"] == []

    def test_an_event_break_demands_high_confidence(self):
        """A break-action event tripped on medium confidence is demoted to review — a
        documented fact fires the rule, an inference summons the owner."""
        doc = committed_doc(triggers=[question_trigger(
            "T9", kind="event", action="break", question="Has the CEO departed?")])
        result = monitor.check_thesis(doc, bundle=None,
                                      verdicts=self._verdict(True, "medium", "T9"),
                                      as_of="w1")
        assert result["status"] == "under_review" and result["broken_by"] == []
        doc = committed_doc(triggers=[question_trigger(
            "T9", kind="event", action="break", question="Has the CEO departed?")])
        result = monitor.check_thesis(doc, bundle=None,
                                      verdicts=self._verdict(True, "high", "T9"),
                                      as_of="w2")
        assert result["status"] == "broken" and result["broken_by"] == ["T9"]


class TestMonitorBrief:
    def _commit(self, tmp_path, doc):
        committed = tmp_path / "committed"
        committed.mkdir(parents=True, exist_ok=True)
        (committed / f"{doc['symbol']}.json").write_text(json.dumps(doc))

    def test_the_brief_lists_only_judgement_questions(self, tmp_path):
        """Metric triggers are answered by arithmetic; sending them to an agent would be
        inviting an opinion about a fact."""
        self._commit(tmp_path, committed_doc())
        path = monitor.brief(tmp_path, as_of="2026-08-08")
        text = path.read_text()
        assert "T2" in text and "T3" in text        # the narrative + event questions
        assert "T1" not in text                     # the metric trigger
        questions = json.loads((path.parent / "questions.json").read_text())
        assert {q["trigger_id"] for q in questions} == {"T2", "T3"}

    def test_no_judgement_triggers_writes_no_order(self, tmp_path):
        """Inventing a question would be the open-ended news scanning the design
        forbids."""
        self._commit(tmp_path, committed_doc(triggers=[metric_trigger()]))
        assert monitor.brief(tmp_path, as_of="2026-08-08") is None

    def test_verdicts_load_by_symbol_and_trigger(self, tmp_path):
        path = tmp_path / "verdicts.json"
        path.write_text(json.dumps([
            {"symbol": "AAA", "trigger_id": "T2", "tripped": False,
             "confidence": "low", "evidence": "nothing found", "sources": []},
            {"symbol": "BBB", "trigger_id": "T9", "tripped": True,
             "confidence": "high", "evidence": "filed", "sources": ["x"]},
        ]))
        loaded = monitor.load_verdicts(path)
        assert loaded["AAA"]["T2"]["tripped"] is False
        assert loaded["BBB"]["T9"]["confidence"] == "high"

    def test_an_unattributable_verdict_is_dropped_not_guessed(self, tmp_path):
        path = tmp_path / "verdicts.json"
        path.write_text(json.dumps([{"tripped": True, "confidence": "high",
                                     "evidence": "?", "sources": []}]))
        assert monitor.load_verdicts(path) == {}

    def test_a_non_array_verdicts_file_is_refused(self, tmp_path):
        path = tmp_path / "verdicts.json"
        path.write_text(json.dumps({"symbol": "AAA"}))
        with pytest.raises(deskwork.OrderError, match="must be a JSON ARRAY"):
            monitor.load_verdicts(path)


class TestWeeklyRun:
    def test_run_updates_files_and_writes_the_report(self, tmp_path, monkeypatch):
        committed = tmp_path / "theses" / "committed"
        committed.mkdir(parents=True)
        (committed / "AAA.json").write_text(json.dumps(
            committed_doc(triggers=[metric_trigger(checks=1)])))
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 8.0})
        report = monitor.run(theses_dir=tmp_path / "theses",
                             bundles_by_symbol={"AAA": {"symbol": "AAA"}},
                             as_of="2026-08-08",
                             reports_dir=tmp_path / "reports")
        assert report[0]["status"] == "broken"
        saved = json.loads((committed / "AAA.json").read_text())
        assert saved["status"] == "broken"
        rendered = (tmp_path / "reports" / "monitor-2026-08-08.md").read_text()
        assert "ignoring cost basis" in rendered           # FR7 in the owner's face
        assert "executes nothing" in rendered              # FR11 beside it

    def test_all_intact_says_no_action_needed(self, tmp_path, monkeypatch):
        committed = tmp_path / "theses" / "committed"
        committed.mkdir(parents=True)
        (committed / "AAA.json").write_text(json.dumps(
            committed_doc(triggers=[metric_trigger(checks=1)])))
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 25.0})
        monitor.run(theses_dir=tmp_path / "theses",
                    bundles_by_symbol={"AAA": {"symbol": "AAA"}},
                    as_of="2026-08-08", reports_dir=tmp_path / "reports")
        rendered = (tmp_path / "reports" / "monitor-2026-08-08.md").read_text()
        assert "No action needed" in rendered              # FR4, first-class

    def test_one_corrupt_thesis_cannot_silence_the_whole_monitor(self, tmp_path,
                                                                 monkeypatch):
        """Without isolation a corrupt file raises out of the loop: every later thesis
        goes unchecked and NO report is written — which looks exactly like 'all clear'."""
        committed = tmp_path / "theses" / "committed"
        committed.mkdir(parents=True)
        (committed / "AAA.json").write_text("{ not json")
        (committed / "BBB.json").write_text(json.dumps(
            committed_doc("BBB", triggers=[metric_trigger(checks=1)])))
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 8.0})
        report = monitor.run(theses_dir=tmp_path / "theses",
                             bundles_by_symbol={"BBB": {"symbol": "BBB"}},
                             as_of="2026-08-08",
                             reports_dir=tmp_path / "reports")
        statuses = {e["symbol"]: e["status"] for e in report}
        assert statuses == {"AAA": "error", "BBB": "broken"}
        rendered = (tmp_path / "reports" / "monitor-2026-08-08.md").read_text()
        assert "could not be read" in rendered and "not an all-clear" in rendered

    def test_the_thesis_file_is_written_atomically(self, tmp_path, monkeypatch):
        """A committed thesis is the only copy of portfolio data outside the code repo:
        an interrupted truncate-then-write destroys it."""
        calls = []
        real_replace = monitor.os.replace
        monkeypatch.setattr(monitor.os, "replace",
                            lambda src, dst: (calls.append((src, dst)),
                                              real_replace(src, dst))[1])
        committed = tmp_path / "theses" / "committed"
        committed.mkdir(parents=True)
        (committed / "AAA.json").write_text(json.dumps(committed_doc()))
        monitor.run(theses_dir=tmp_path / "theses", bundles_by_symbol={},
                    as_of="w1", reports_dir=tmp_path / "reports")
        assert calls and str(calls[0][0]).endswith(".json.tmp")
        assert not list(committed.glob("*.tmp"))

    def test_no_committed_theses_renders_the_empty_state(self, tmp_path):
        report = monitor.run(theses_dir=tmp_path / "theses", bundles_by_symbol={},
                             as_of="2026-08-08",
                             reports_dir=tmp_path / "reports")
        assert report == []
        rendered = (tmp_path / "reports" / "monitor-2026-08-08.md").read_text()
        assert "ratify a draft" in rendered.lower() or "No committed theses" in rendered


# --- The model gate (the owner's "best available" rule) -----------------------------------

class TestModelGate:
    """Deleting the API client deleted the one place a model was pinned. These tests hold
    the replacement: the model is read from the harness rather than asked of the agent,
    it is recorded on every artifact, and an unapproved one is refused at both gates."""

    def _real(self, monkeypatch):
        """Drop the module-wide model pin: these tests are about the real resolution,
        not about the isolation the rest of the suite runs under."""
        monkeypatch.undo()

    def _transcript(self, tmp_path, *models):
        path = tmp_path / "session.jsonl"
        path.write_text("\n".join(
            json.dumps({"type": "assistant", "message": {"model": m, "content": []}})
            for m in models), encoding="utf-8")
        return path

    def test_the_model_is_read_from_the_harness_not_asked_of_the_agent(self, tmp_path,
                                                                       monkeypatch):
        self._real(monkeypatch)
        path = self._transcript(tmp_path, "claude-haiku-4-5-20251001", APPROVED)
        assert deskwork.observed_model(path) == APPROVED

    def test_synthetic_turns_are_not_mistaken_for_a_model(self, tmp_path, monkeypatch):
        """Harness-generated turns carry no model; reading one as the answer would let a
        cancellation notice stand in for the thing that did the work."""
        self._real(monkeypatch)
        path = self._transcript(tmp_path, APPROVED, "<synthetic>")
        assert deskwork.observed_model(path) == APPROVED

    def test_no_transcript_is_not_an_approval(self, tmp_path, monkeypatch):
        self._real(monkeypatch)
        assert deskwork.observed_model(tmp_path / "nope.jsonl") is None
        info, problems = deskwork.resolve_model(None, transcript=tmp_path / "nope.jsonl")
        assert info["approved"] is False
        assert any("no model recorded" in p for p in problems)

    def test_an_unapproved_model_is_refused(self, tmp_path, monkeypatch):
        self._real(monkeypatch)
        path = self._transcript(tmp_path, "claude-haiku-4-5-20251001")
        info, problems = deskwork.resolve_model(transcript=path)
        assert info["id"] == "claude-haiku-4-5-20251001" and info["approved"] is False
        assert any("best available" in p for p in problems)

    def test_a_declaration_contradicting_the_harness_is_refused(self, tmp_path,
                                                                monkeypatch):
        """The declaration is only worth anything because it is cross-checked: an agent
        that could name its own model would be trusted for part of the contract."""
        self._real(monkeypatch)
        path = self._transcript(tmp_path, "claude-haiku-4-5-20251001")
        _, problems = deskwork.resolve_model(APPROVED, transcript=path)
        assert any("mismatch" in p for p in problems)

    def test_a_declaration_stands_alone_but_says_it_is_unverified(self, tmp_path,
                                                                  monkeypatch):
        """OpenClaw and bare shells keep no transcript. The declaration is then all there
        is — allowed, but never dressed up as verified."""
        self._real(monkeypatch)
        info, problems = deskwork.resolve_model(APPROVED,
                                                transcript=tmp_path / "nope.jsonl")
        assert problems == [] and info["provenance"] == "declared"
        assert "NOT independently verified" in deskwork.model_note(info)


class TestModelGateAtTheSeams:
    def _agent_writes(self, tmp_path, symbol="AAA"):
        out = tmp_path / "drafts" / symbol
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.md").write_text("# Report\nlong analysis")
        (out / "summary.md").write_text(f"{thesis.SUMMARY_HEADING}\nplain words")
        (out / "thesis.json").write_text(json.dumps(draft(symbol)))
        return out

    def test_record_stamps_the_model_onto_the_draft(self, tmp_path):
        self._agent_writes(tmp_path)
        doc = thesis.record("AAA", theses_dir=tmp_path)
        assert doc["agent"] == {"id": APPROVED, "provider": "anthropic",
                                "provenance": "observed", "approved": True}

    def test_record_refuses_an_unapproved_model_and_says_why_on_disk(self, tmp_path,
                                                                     monkeypatch):
        """A refusal that leaves no trace is the failure mode this seam exists to stop:
        the record must still be written, carrying the reason."""
        monkeypatch.setattr(deskwork, "observed_model",
                            lambda transcript=None: "claude-haiku-4-5-20251001")
        self._agent_writes(tmp_path)
        with pytest.raises(deskwork.OrderError, match="best available"):
            thesis.record("AAA", theses_dir=tmp_path)
        saved = json.loads((tmp_path / "drafts" / "AAA" / "record.json").read_text())
        assert saved["agent"]["approved"] is False
        assert any("best available" in p for p in saved["validation_problems"])

    def test_the_gate_re_checks_the_model_rather_than_trusting_the_record(self, tmp_path):
        """record.json is an ordinary file on disk. If the Gate trusted its `approved`
        flag, hand-editing one line would launder a thesis written by any model at all."""
        out = tmp_path / "drafts" / "AAA"
        out.mkdir(parents=True)
        (out / "record.json").write_text(json.dumps(
            {"symbol": "AAA", "status": "draft", "thesis": draft(),
             "agent": agent_block("claude-haiku-4-5-20251001")}))
        with pytest.raises(ValueError, match="not approved"):
            thesis.ratify("AAA", theses_dir=tmp_path, ask=lambda _: "high")

    def test_the_monitor_refuses_verdicts_from_an_unapproved_model(self, tmp_path,
                                                                   monkeypatch):
        monkeypatch.setattr(deskwork, "observed_model",
                            lambda transcript=None: "claude-haiku-4-5-20251001")
        committed = tmp_path / "theses" / "committed"
        committed.mkdir(parents=True)
        (committed / "AAA.json").write_text(json.dumps(
            committed_doc(triggers=[question_trigger()])))
        with pytest.raises(deskwork.OrderError, match="best available"):
            monitor.run(theses_dir=tmp_path / "theses", bundles_by_symbol={},
                        verdicts={"AAA": {"T2": {"tripped": True,
                                                 "confidence": "high"}}},
                        as_of="2026-08-08", reports_dir=tmp_path / "reports")

    def test_a_metric_only_run_needs_no_model_at_all(self, tmp_path, monkeypatch):
        """The gate binds JUDGEMENT, not arithmetic. Blocking a metric-only sweep because
        no agent was involved would turn a safety rule into an outage."""
        monkeypatch.setattr(deskwork, "observed_model", lambda transcript=None: None)
        committed = tmp_path / "theses" / "committed"
        committed.mkdir(parents=True)
        (committed / "AAA.json").write_text(json.dumps(
            committed_doc(triggers=[metric_trigger(checks=1)])))
        monkeypatch.setattr(monitor.scoring, "evaluate",
                            lambda bundle: {"ofcf_margin": 8.0})
        report = monitor.run(theses_dir=tmp_path / "theses",
                             bundles_by_symbol={"AAA": {"symbol": "AAA"}},
                             as_of="2026-08-08", reports_dir=tmp_path / "reports")
        assert report[0]["status"] == "broken"
        rendered = (tmp_path / "reports" / "monitor-2026-08-08.md").read_text()
        assert "no agent judgement was used" in rendered

    def test_the_report_names_the_model_that_answered_the_questions(self, tmp_path):
        committed = tmp_path / "theses" / "committed"
        committed.mkdir(parents=True)
        (committed / "AAA.json").write_text(json.dumps(
            committed_doc(triggers=[question_trigger()])))
        monitor.run(theses_dir=tmp_path / "theses", bundles_by_symbol={},
                    verdicts={"AAA": {"T2": {"tripped": False, "confidence": "high",
                                             "evidence": "nothing found"}}},
                    as_of="2026-08-08", reports_dir=tmp_path / "reports")
        rendered = (tmp_path / "reports" / "monitor-2026-08-08.md").read_text()
        assert APPROVED in rendered and "harness transcript" in rendered


class TestTwoProviderModelGate:
    """(the autouse fixture pins observed_model; these tests override it to None so the
    DECLARED id is what the gate judges)"""

    @pytest.fixture(autouse=True)
    def _no_transcript(self, monkeypatch):
        monkeypatch.setattr(deskwork, "observed_model", lambda transcript=None: None)

    """The runtime is a SUBSCRIPTION (2026-08-05): Claude or ChatGPT, never an API key.
    'Best available' therefore reads per provider — one flat list would let a weak model
    from the other vendor inherit the approval of a strong one."""

    def test_provider_is_read_from_the_id(self):
        assert deskwork.provider_of("claude-opus-5") == "anthropic"
        assert deskwork.provider_of("gpt-5.2") == "openai"
        assert deskwork.provider_of("o3-pro") == "openai"
        assert deskwork.provider_of("llama-3") is None      # unknown, never assumed

    def test_unknown_provider_is_refused_not_assumed(self):
        info, problems = deskwork.resolve_model("llama-3", transcript=None)
        assert info["approved"] is False
        assert any("announces no provider" in p for p in problems)

    def test_a_provider_with_no_approved_list_is_refused_loudly(self, monkeypatch):
        monkeypatch.setattr(deskwork, "APPROVED_MODELS",
                            {"anthropic": ("claude-opus-5",), "openai": ()})
        info, problems = deskwork.resolve_model("gpt-5.2", transcript=None)
        assert info["approved"] is False and info["provider"] == "openai"
        assert any("no approved model yet" in p for p in problems)

    def test_an_approved_openai_model_passes_once_the_owner_lists_it(self, monkeypatch):
        monkeypatch.setattr(deskwork, "APPROVED_MODELS",
                            {"anthropic": ("claude-opus-5",), "openai": ("gpt-5.2",)})
        info, problems = deskwork.resolve_model("gpt-5.2", transcript=None)
        assert info["approved"] is True and info["provider"] == "openai"
        assert problems == []
        assert "openai" in deskwork.model_note(info)

    def test_owner_approved_gpt_56_sol_is_accepted(self):
        info, problems = deskwork.resolve_model("gpt-5.6-sol", transcript=None)
        assert problems == []
        assert info == {
            "id": "gpt-5.6-sol", "provider": "openai",
            "provenance": "declared", "approved": True,
        }

    def test_cross_provider_approval_does_not_leak(self, monkeypatch):
        monkeypatch.setattr(deskwork, "APPROVED_MODELS",
                            {"anthropic": ("claude-opus-5",), "openai": ("gpt-5.2",)})
        info, problems = deskwork.resolve_model("claude-haiku-9", transcript=None)
        assert info["approved"] is False
        assert any("not approved" in p and "anthropic" in p for p in problems)


class TestProductionThesisFreshness:
    def row(self):
        return {
            "security_key": "sec-aaa",
            "symbol": "AAA",
            "rank": 1,
            "card": {"score": 70.0, "pct": 80.0, "band": "Exceptional",
                     "evidence": "full", "generated_at": "volatile"},
            "bundle": {
                "companyfacts_hash": "facts-a",
                "accessions": ["0001", "0002"],
                "price_observation_id": 42,
                "metric_evidence_ids": [9, 4],
                "generated_at": "also volatile",
            },
        }

    def test_research_fingerprint_is_stable_and_ignores_render_timestamps(self):
        left = self.row()
        right = {
            "bundle": dict(reversed(list(left["bundle"].items()))),
            "card": dict(reversed(list(left["card"].items()))),
            "rank": 1, "symbol": "AAA", "security_key": "sec-aaa",
        }
        right["card"]["generated_at"] = "changed"
        right["bundle"]["generated_at"] = "changed"
        assert thesis.research_fingerprint(left, "scout-v1") == \
            thesis.research_fingerprint(right, "scout-v1")

    @pytest.mark.parametrize("path,value", [
        (("rank",), 2),
        (("card", "score"), 71.0),
        (("bundle", "companyfacts_hash"), "facts-b"),
        (("bundle", "price_observation_id"), 43),
        (("bundle", "accessions"), ["0003"]),
    ])
    def test_research_fingerprint_changes_with_evidence_or_rank(self, path, value):
        before = self.row()
        after = self.row()
        target = after
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        assert thesis.research_fingerprint(before, "scout-v1") != \
            thesis.research_fingerprint(after, "scout-v1")

    def test_evaluation_decision_is_explicit(self):
        assert thesis.evaluation_decision(None, "a", False) == \
            ("CREATED", "NEW_TOP_MEMBER")
        assert thesis.evaluation_decision("a", "a", False) == \
            ("REUSED", "INPUTS_UNCHANGED")
        assert thesis.evaluation_decision("a", "b", False) == \
            ("REFRESHED", "INPUTS_CHANGED")
        assert thesis.evaluation_decision("a", "a", True) == \
            ("REFRESHED", "RESEARCH_STALE")


class TestMungerGatesTheDeskFeed:
    """Owner-directed 2026-08-08: "omitted or munger vetos should not be a thesis."

    The constitution's order is circle -> Hell-No -> Buffett dossier. Before this, the
    desk feed ranked on the scorecard alone, so names the inversion layer had already
    named a failure mode for still consumed work orders.
    """

    CARD = {"pct": 95, "band": "Exceptional", "evidence": "full",
            "score": 95, "available_max": 100}

    def _row(self, symbol, verdict, severe=0, caution=0):
        return {"symbol": symbol, "card": dict(self.CARD),
                "inversion": {"verdict": verdict,
                              "coverage": {"severe": severe, "caution": caution}}}

    def test_ruinous_and_fragile_names_never_reach_the_feed(self):
        rows = [
            self._row("GOOD", "Ordinary"),
            self._row("RUIN", "Ruinous", severe=3),
            self._row("FRAG", "Fragile", severe=2),
            self._row("ROBUST", "Robust"),
        ]
        chosen = [r["symbol"] for r in thesis.top_symbols(rows, 400)]
        assert "RUIN" not in chosen and "FRAG" not in chosen
        assert "GOOD" in chosen and "ROBUST" in chosen

    def test_one_severe_probe_is_enough_to_refuse_even_inside_ordinary(self):
        """The calibrated ladder puts a single severe finding inside Ordinary. A named
        way to lose money must not reach a thesis just because the ladder is lenient."""
        rows = [self._row("KEEP", "Ordinary", severe=0),
                self._row("NAMED", "Ordinary", severe=1)]
        chosen = [r["symbol"] for r in thesis.top_symbols(rows, 400)]
        assert chosen == ["KEEP"]

    def test_unknown_is_not_a_veto(self):
        """Unknown means the layer could not certify — a fact about the evidence, not a
        named failure mode. It still has to clear every other gate."""
        rows = [self._row("UNK", "Unknown")]
        assert [r["symbol"] for r in thesis.top_symbols(rows, 400)] == ["UNK"]

    def test_a_row_without_an_inversion_result_is_not_excluded(self):
        """Absence of evidence is not a veto — 'refuse, never guess' cuts both ways."""
        rows = [{"symbol": "NOINV", "card": dict(self.CARD)}]
        assert [r["symbol"] for r in thesis.top_symbols(rows, 400)] == ["NOINV"]

    def test_the_gate_runs_before_the_rank_is_taken(self):
        """A refused name must not consume one of the 1% slots: the survivors backfill
        it, rather than the feed coming back one short."""
        rows = [self._row("RUIN", "Ruinous", severe=3),      # would rank first
                self._row("A", "Ordinary"), self._row("B", "Ordinary")]
        rows[0]["card"]["pct"] = 99
        chosen = [r["symbol"] for r in thesis.top_symbols(rows, 100)]   # 1 slot
        assert chosen == ["A"] or chosen == ["B"]
        assert "RUIN" not in chosen
