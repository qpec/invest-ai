"""The thesis engine: the LLM loop, the builder's validation contract, and the monitor.

Fully offline (network in a test is a test failure): every LLM interaction goes through a
scripted FakeTransport, and metric evaluation is fed canned scoring.evaluate output. What
these tests protect is the CONTRACT the design states out loud — a pause_turn is resumed
rather than read as an answer, a refusal is an error rather than an empty thesis, an
unvalidatable trigger cannot be ratified, judgement never fires the sell rule alone, and
a missing API key reads as UNCHECKED rather than intact.
"""
import json

import pytest

import llm
import monitor
import scoring
import thesis


# --- Scripted transport -------------------------------------------------------------------

def response(stop_reason="end_turn", content=None, usage=None, stop_details=None):
    return {"stop_reason": stop_reason, "content": content or [],
            "usage": usage or {"input_tokens": 100, "output_tokens": 50},
            "stop_details": stop_details}


def text(t):
    return {"type": "text", "text": t}


def tool_use(name, payload, block_id="toolu_1"):
    return {"type": "tool_use", "id": block_id, "name": name, "input": payload}


class FakeTransport:
    """Plays back a script of responses and records every payload sent."""

    def __init__(self, script):
        self.script = list(script)
        self.payloads = []
        self.betas = []

    def __call__(self, payload, betas=()):
        self.payloads.append(payload)
        self.betas.append(tuple(betas))
        if not self.script:
            raise AssertionError("transport called more times than scripted")
        return self.script.pop(0)


def make_client(script, **kwargs):
    return llm.Client(transport=FakeTransport(script), **kwargs)


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


# --- llm.Client ---------------------------------------------------------------------------

class TestClientLoop:
    def test_captures_the_strict_tool_and_stops(self):
        client = make_client([response("tool_use", [
            text("report text"), tool_use("record_thesis", {"symbol": "AAA"})])])
        result = client.run(system="s", user="u", tools=[], capture_tool="record_thesis")
        assert result["captured"] == {"symbol": "AAA"}
        assert result["text"] == "report text"

    def test_pause_turn_is_resumed_not_returned(self):
        """A pause_turn is an UNFINISHED server-tool turn. Treating it as final would
        silently truncate a research run — the loop must re-send and continue."""
        client = make_client([
            response("pause_turn", [text("searching...")]),
            response("tool_use", [tool_use("record_thesis", {"symbol": "AAA"})]),
        ])
        result = client.run(system="s", user="u", tools=[], capture_tool="record_thesis")
        assert result["captured"] == {"symbol": "AAA"}
        resumed = client.transport.payloads[1]["messages"]
        assert resumed[1]["role"] == "assistant"          # the paused turn went back

    def test_refusal_is_an_error_not_an_empty_result(self):
        client = make_client([response("refusal", [],
                                       stop_details={"category": "cyber",
                                                     "explanation": "declined"})])
        with pytest.raises(llm.RefusalError) as excinfo:
            client.run(system="s", user="u", tools=[], capture_tool="record_thesis")
        assert excinfo.value.category == "cyber"

    def test_end_turn_without_the_tool_reports_no_capture(self):
        client = make_client([response("end_turn", [text("just prose")])])
        result = client.run(system="s", user="u", tools=[], capture_tool="record_thesis")
        assert result["captured"] is None
        assert result["stop_reason"] == "end_turn"

    def test_fallbacks_default_is_sent_with_its_beta_header(self):
        client = make_client([response("end_turn")])
        client.run(system="s", user="u", tools=[], capture_tool="x")
        assert client.transport.payloads[0]["fallbacks"] == "default"
        assert llm.FALLBACK_BETA in client.transport.betas[0]

    def test_fallbacks_opt_out_sends_neither(self):
        client = make_client([response("end_turn")], fallbacks=None)
        client.run(system="s", user="u", tools=[], capture_tool="x")
        assert "fallbacks" not in client.transport.payloads[0]
        assert client.transport.betas[0] == ()

    def test_no_sampling_or_thinking_params_are_ever_sent(self):
        """claude-opus-5 rejects temperature/top_p/top_k, and thinking is on by default —
        the payload must carry none of them."""
        client = make_client([response("end_turn")])
        client.run(system="s", user="u", tools=[], capture_tool="x")
        payload = client.transport.payloads[0]
        for banned in ("temperature", "top_p", "top_k", "thinking"):
            assert banned not in payload

    def test_the_loop_is_bounded(self):
        client = make_client([response("pause_turn", [text("...")])] * 3, max_turns=3)
        with pytest.raises(llm.LLMError, match="no result after 3 turns"):
            client.run(system="s", user="u", tools=[], capture_tool="x")

    def test_usage_accumulates_across_turns_and_prices_the_run(self):
        client = make_client([
            response("pause_turn", usage={"input_tokens": 1000, "output_tokens": 100}),
            response("end_turn", usage={"input_tokens": 2000, "output_tokens": 300}),
        ])
        result = client.run(system="s", user="u", tools=[], capture_tool="x")
        usage = result["usage"]
        assert usage["turns"] == 2
        assert usage["input_tokens"] == 3000 and usage["output_tokens"] == 400
        expected = (3000 * 5.00 + 400 * 25.00) / 1_000_000
        assert usage["estimated_cost_usd"] == pytest.approx(expected)


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


# --- thesis.ratify (the Gate) -------------------------------------------------------------

class TestRatify:
    def _write_draft(self, tmp_path, doc):
        out = tmp_path / "drafts" / doc["thesis"]["symbol"]
        out.mkdir(parents=True)
        (out / "thesis.json").write_text(json.dumps(doc))

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

class TestBuild:
    def _row(self, monkeypatch):
        monkeypatch.setattr(thesis.scoring, "evaluate",
                            lambda bundle: {key: 10.0 for key, _, _
                                            in thesis.METRICS.values()})
        card = {"score": 70.0, "available_max": 87, "pct": 80, "band": "Exceptional",
                "evidence": "full", "why": {}}
        inv = {"verdict": "Ordinary", "verdict_meaning": "Normal business risk",
               "failure_modes": ["the price fell 45%"], "coverage": {"severe": 0}}
        return {"symbol": "AAA"}, card, inv

    def test_build_writes_the_three_artifacts(self, tmp_path, monkeypatch):
        bundle, card, inv = self._row(monkeypatch)
        client = make_client([response("tool_use", [
            text(f"# Report\nlong analysis\n\n{thesis.SUMMARY_HEADING}\nplain words"),
            tool_use("record_thesis", draft())])])
        doc = thesis.build("AAA", bundle, card, inv, client=client,
                           theses_dir=tmp_path, with_filings=False)
        assert doc["status"] == "draft" and doc["validation_problems"] == []
        base = tmp_path / "drafts" / "AAA"
        assert "long analysis" in (base / "report.md").read_text()
        summary = (base / "summary.md").read_text()
        assert summary.startswith(thesis.SUMMARY_HEADING)
        assert thesis.SUMMARY_HEADING not in (base / "report.md").read_text()
        saved = json.loads((base / "thesis.json").read_text())
        assert saved["thesis"]["symbol"] == "AAA"
        assert saved["usage"]["estimated_cost_usd"] is not None

    def test_a_run_that_never_records_is_an_error_not_an_empty_thesis(
            self, tmp_path, monkeypatch):
        bundle, card, inv = self._row(monkeypatch)
        client = make_client([response("end_turn", [text("prose only")])])
        with pytest.raises(llm.LLMError, match="without calling record_thesis"):
            thesis.build("AAA", bundle, card, inv, client=client,
                         theses_dir=tmp_path, with_filings=False)

    def test_an_invalid_draft_is_saved_with_its_problems_named(
            self, tmp_path, monkeypatch):
        """A bad draft is still worth keeping for the Gate — but its problems ride along
        and ratification will refuse it until they are fixed."""
        bundle, card, inv = self._row(monkeypatch)
        bad = draft(triggers=[metric_trigger(metric="vibes"), question_trigger(),
                              question_trigger("T3")])
        client = make_client([response("tool_use", [tool_use("record_thesis", bad)])])
        doc = thesis.build("AAA", bundle, card, inv, client=client,
                           theses_dir=tmp_path, with_filings=False)
        assert doc["validation_problems"]

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
    def _verdict(self, tripped, confidence):
        return response("tool_use", [tool_use("record_verdict", {
            "tripped": tripped, "confidence": confidence,
            "evidence": "the filing says so", "sources": ["sec.gov"]})])

    def test_no_llm_means_unchecked_loudly(self):
        doc = committed_doc(triggers=[question_trigger()])
        result = monitor.check_thesis(doc, bundle=None, client=None, as_of="w1")
        assert result["status"] == "intact" and result["unchecked"] == ["T2"]
        assert "UNCHECKED" in result["triggers"][0]["detail"]

    def test_a_tripped_narrative_reviews_and_never_breaks(self):
        doc = committed_doc(triggers=[question_trigger(action="review")])
        client = make_client([self._verdict(True, "high")])
        result = monitor.check_thesis(doc, bundle=None, client=client, as_of="w1")
        assert result["status"] == "under_review"
        assert result["broken_by"] == []

    def test_an_event_break_demands_high_confidence(self):
        """A break-action event tripped on medium confidence is demoted to review this
        week — a documented fact fires the rule, an inference summons the owner."""
        doc = committed_doc(triggers=[question_trigger(
            "T9", kind="event", action="break", question="Has the CEO departed?")])
        client = make_client([self._verdict(True, "medium")])
        result = monitor.check_thesis(doc, bundle=None, client=client, as_of="w1")
        assert result["status"] == "under_review" and result["broken_by"] == []
        client = make_client([self._verdict(True, "high")])
        result = monitor.check_thesis(doc, bundle=None, client=client, as_of="w2")
        assert result["status"] == "broken" and result["broken_by"] == ["T9"]


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
                             client=None, as_of="2026-08-08",
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
                    client=None, as_of="2026-08-08", reports_dir=tmp_path / "reports")
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
                             client=None, as_of="2026-08-08",
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
                    client=None, as_of="w1", reports_dir=tmp_path / "reports")
        assert calls and str(calls[0][0]).endswith(".json.tmp")
        assert not list(committed.glob("*.tmp"))

    def test_no_committed_theses_renders_the_empty_state(self, tmp_path):
        report = monitor.run(theses_dir=tmp_path / "theses", bundles_by_symbol={},
                             client=None, as_of="2026-08-08",
                             reports_dir=tmp_path / "reports")
        assert report == []
        rendered = (tmp_path / "reports" / "monitor-2026-08-08.md").read_text()
        assert "ratify a draft" in rendered.lower() or "No committed theses" in rendered
