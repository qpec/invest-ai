"""The desk site generator — the parts a browser cannot excuse.

Fully offline (R15): everything here runs on handcrafted models, never the export.
"""
from __future__ import annotations

import json

import webapp


class TestMarkdown:
    def test_escapes_before_rendering(self):
        out = webapp.md_html("hello <script>alert(1)</script> **bold**")
        assert "<script>alert" not in out
        assert "&lt;script&gt;" in out and "<strong>bold</strong>" in out

    def test_ordered_list_numbers_once(self):
        """The regex that strips the source numbering was double-escaped in the first
        cut, so <ol> rendered '1. 1.'."""
        out = webapp.md_html("1. first\n2. second")
        assert "<ol>" in out and "<li>first</li>" in out
        assert "1." not in out.replace("<ol>", "")

    def test_links_only_http(self):
        out = webapp.md_html("[x](javascript:alert(1)) [y](https://a.example/b)")
        assert "javascript:" not in out.replace("[x](javascript:alert(1))", "")
        assert '<a href="https://a.example/b"' in out

    def test_tables_render_and_escape(self):
        out = webapp.md_html("| a | b |\n|---|---|\n| <i>x</i> | y |")
        assert "<table>" in out and "&lt;i&gt;x&lt;/i&gt;" in out


class TestPayload:
    def test_script_breakout_is_neutralised(self):
        blob = webapp._payload_json({"x": "</script><script>window.PWNED=1"}, {})
        assert "</script" not in blob

    def test_owner_only_fields_stripped(self):
        doc = {"symbol": "AAA", "conviction": "high",
               "circle_of_competence": "cloud", "thesis": {}}
        cleaned = webapp.strip_owner_fields(doc)
        assert "conviction" not in cleaned and "circle_of_competence" not in cleaned
        assert cleaned["symbol"] == "AAA"


class TestTriggerEval:
    def test_safety_margin_is_positive_when_safe_either_direction(self):
        doc = {"triggers": [
            {"id": "below", "kind": "metric", "action": "break", "statement": "",
             "metric": "owner_fcf_margin_pct", "op": "<", "threshold": 10.0,
             "consecutive_checks": 2, "question": None},
            {"id": "above", "kind": "metric", "action": "break", "statement": "",
             "metric": "net_debt_to_ebitda", "op": ">", "threshold": 2.0,
             "consecutive_checks": 2, "question": None},
        ]}
        rows = webapp.trigger_eval(doc, {"owner_fcf_margin_pct": 16.4,
                                         "net_debt_to_ebitda": 1.2})
        by_id = {r["id"]: r for r in rows}
        assert by_id["below"]["hit"] is False and by_id["below"]["distance_pct"] == 64.0
        assert by_id["above"]["hit"] is False and by_id["above"]["distance_pct"] == 40.0

    def test_zero_threshold_measures_in_points(self):
        doc = {"triggers": [{"id": "t", "kind": "metric", "action": "review",
                             "statement": "", "metric": "share_count_trend_pct_per_year",
                             "op": ">", "threshold": 0.0, "consecutive_checks": 2,
                             "question": None}]}
        row = webapp.trigger_eval(doc, {"share_count_trend_pct_per_year": -12.0})[0]
        assert row["margin_kind"] == "points" and row["distance_pct"] == 12.0

    def test_tripped_is_reported_not_hidden(self):
        doc = {"triggers": [{"id": "t", "kind": "metric", "action": "break",
                             "statement": "", "metric": "gross_margin_pct",
                             "op": "<", "threshold": 50.0, "consecutive_checks": 2,
                             "question": None}]}
        row = webapp.trigger_eval(doc, {"gross_margin_pct": 43.0})[0]
        assert row["hit"] is True and row["distance_pct"] == -14.0

    def test_uncomputable_metric_shows_no_number(self):
        doc = {"triggers": [{"id": "t", "kind": "metric", "action": "break",
                             "statement": "", "metric": "net_debt_to_ebitda",
                             "op": ">", "threshold": 2.0, "consecutive_checks": 2,
                             "question": None}]}
        row = webapp.trigger_eval(doc, {"net_debt_to_ebitda": None})[0]
        assert row["current"] is None and row["hit"] is None


class TestProvenance:
    def test_edgar_fill_and_refinement_are_distinguished(self):
        pre = {"a": None, "b": 5.0, "c": 7.0}
        post = {"a": 1.0, "b": 5.0, "c": 8.0}
        out = webapp.provenance(pre, post)
        assert out == {"a": webapp.SRC_EDGAR, "b": webapp.SRC_EXPORT,
                       "c": webapp.SRC_REFINED}

    def test_never_enriched_is_export_or_absent(self):
        out = webapp.provenance(None, {"a": 1.0, "b": None})
        assert out == {"a": webapp.SRC_EXPORT, "b": None}


class TestSite:
    def _model(self):
        return {
            "as_of": "2026-08-01", "generated": "2026-08-03", "source": "test",
            "counts": {"screened": 2, "picks": 1, "top": 1, "drafts": 0,
                       "committed": 0, "enriched": 0, "enriched_filled": 0},
            "rows": [
                {"s": "AAA", "n": "Alpha", "sec": "IT", "mc": 1e9, "pct": 90,
                 "band": "Exceptional", "ev": "full", "verdict": "Ordinary",
                 "sev": 0, "cau": 1, "pick": True, "top": 1, "rk": 0,
                 "grade": None, "reg": {}},
                {"s": "ZZZ", "n": "Omega <i>&", "sec": "IT", "mc": None, "pct": None,
                 "band": "NO PRICE", "ev": "thin", "verdict": "Unknown",
                 "sev": 0, "cau": 0, "pick": False, "top": None, "rk": 1,
                 "grade": "INSUFFICIENT", "reg": {}},
            ],
            "details": {"AAA": {"card": {}, "inv": {}, "scored": {}, "reg": {},
                        "mc": 1e9},
                        "ZZZ": {"card": {}, "inv": {}, "scored": {}, "reg": {},
                        "mc": None}},
            "charts": {"bands": [], "verdicts": [], "coverage": []},
            "units": {}, "thesis": {"top": [], "drafts": []},
            "monitor": {"committed": [], "next_run": "2026-08-08", "preview": None},
        }

    def test_write_site_shards_every_symbol_exactly_once(self, tmp_path):
        webapp.write_site(self._model(), tmp_path)
        shards = {}
        for path in (tmp_path / "data").glob("d-*.json"):
            for symbol in json.loads(path.read_text()):
                assert symbol not in shards, f"{symbol} in two shards"
                shards[symbol] = path.name
        assert set(shards) == {"AAA", "ZZZ"}

    def test_page_embeds_picks_only_and_survives_hostile_names(self, tmp_path):
        out = webapp.write_site(self._model(), tmp_path)
        page = out.read_text(encoding="utf-8")
        payload = page.split("window.__SITE__ = ", 1)[1].split("</script>", 1)[0]
        assert "PWNED" not in page
        assert '"AAA"' in payload
        # ZZZ's detail is shard-only; the page itself must not carry it inline.
        embedded = payload.split('"details":', 1)[1]
        assert '"ZZZ":{' not in embedded.split('"rows":')[0]

    def test_owner_fields_cannot_reach_the_page(self, tmp_path, monkeypatch):
        """Belt and braces at the render layer: even a committed thesis with FR9 fields
        present must not put those words into the payload as keys."""
        model = self._model()
        model["monitor"]["committed"] = [webapp.strip_owner_fields(
            {"symbol": "AAA", "status": "intact", "version": 1,
             "conviction": "high", "circle_of_competence": "day job",
             "trigger_state": {}, "triggers": []})]
        page = webapp.write_site(model, tmp_path).read_text(encoding="utf-8")
        assert '"conviction"' not in page and '"circle_of_competence"' not in page


class TestMoreReviewRegressions:
    def test_refused_draft_with_malformed_op_renders_not_crashes(self):
        """Review 2026-08-03: record keeps refused drafts on disk BY DESIGN, and one
        malformed op crashed the whole site build with a KeyError."""
        doc = {"triggers": [{"id": "bad", "kind": "metric", "action": "break",
                             "statement": "", "metric": "roic_pct", "op": "!!",
                             "threshold": 5.0, "consecutive_checks": 1,
                             "question": None}]}
        row = webapp.trigger_eval(doc, {"roic_pct": 20.0})[0]
        assert row["hit"] is None and row["distance_pct"] is None

    def test_trigger_arithmetic_agrees_with_the_monitor(self):
        """The page shows distance-to-trigger; the monitor decides trips. Same trigger,
        same value -> the hit verdicts must agree, or the site is a lie about the
        monitor."""
        import monitor
        trigger = {"id": "t", "kind": "metric", "action": "break", "statement": "",
                   "metric": "owner_fcf_margin_pct", "op": "<", "threshold": 10.0,
                   "consecutive_checks": 1, "question": None}
        for value in (9.99, 10.0, 10.01):
            site = webapp.trigger_eval({"triggers": [trigger]},
                                       {"owner_fcf_margin_pct": value})[0]
            mon = monitor.check_trigger(trigger, symbol="AAA",
                                        evaluated={"ofcf_margin": value},
                                        bundle={}, as_of="2026-08-08")
            assert site["hit"] == mon["tripped"], value

    def test_hard_wrapped_prose_joins_into_one_paragraph(self):
        out = webapp.md_html("one line\nsame paragraph\n\nnew paragraph")
        assert out.count("<p>") == 2
        assert "<p>one line same paragraph</p>" in out

    def test_wrapped_list_items_stay_one_item(self):
        out = webapp.md_html("1. first line\n   wraps here\n2. second")
        assert out.count("<li>") == 2 and "first line wraps here" in out

    def test_table_pipes_inside_code_spans_stay_content(self):
        out = webapp.md_html("| a | b |\n|---|---|\n| `x|y` | z |")
        assert "<code>x|y</code>" in out


class TestNextSaturday:
    def test_regular_week(self):
        assert webapp.next_saturday("2026-08-01") == "2026-08-08"  # a Saturday -> next

    def test_midweek(self):
        assert webapp.next_saturday("2026-08-03") == "2026-08-08"  # Monday -> same week


class TestReviewRegressions:
    def test_link_href_cannot_break_out_of_the_attribute(self):
        """Review 2026-08-03: quote=False escaping left double quotes alive inside the
        regex-built href — a stored-XSS path from agent-authored markdown."""
        evil = '[x](https://a.example/x"onmouseover="alert(1))'
        out = webapp.md_html(evil)
        assert 'onmouseover="alert' not in out
        assert '&quot;onmouseover=&quot;' in out

    def test_share_class_tickers_both_get_enrichment(self, tmp_path, monkeypatch):
        """Review 2026-08-03: a cik->ticker reverse dict collapsed FOX/FOXA onto one
        winner and silently un-enriched the loser."""
        import enrich
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "_tickers.json").write_text(json.dumps({"FOX": 1, "FOXA": 1}))
        (cache / "CIK0000000001.json").write_text(json.dumps({"facts": {}}))
        ciks = enrich.cik_map_cached(cache)
        cached = {p.name for p in cache.glob("CIK*.json")}
        facts = {"FOX": {}, "FOXA": {}}
        symbols = sorted(t for t, c in ciks.items()
                         if t in facts and f"CIK{c:010d}.json" in cached)
        assert symbols == ["FOX", "FOXA"]


class TestDeskActions:
    """The desk surface: inert when published, validated when served."""

    class Args:
        sec_data = "sd"; prices = "px"; universe = "u.csv"; as_of = "2026-08-05"
        enrich_cache = "ec"; theses_dir = "th"; out_dir = "out"; no_shards = False

    def test_published_build_carries_no_token(self):
        """A published page must not be able to drive anyone's desk."""
        payload = webapp._payload_json({"rows": [], "desk": {"enabled": False}}, {})
        assert '"desk":{"enabled":false}' in payload
        assert "token" not in payload
        # and the served build is the one that carries a capability
        served = webapp._payload_json(
            {"rows": [], "desk": {"enabled": True, "token": "secret"}}, {})
        assert '"enabled":true' in served

    def test_unknown_action_and_symbol_are_refused(self):
        args = self.Args()
        argv, err = webapp.desk_command("nope", None, args, {"AAPL"})
        assert argv is None and "unknown action" in err
        argv, err = webapp.desk_command("refresh", "ZZZZ", args, {"AAPL"})
        assert argv is None and err == "unknown symbol"
        # an injection-shaped symbol is refused for the same reason: it is not screened
        argv, err = webapp.desk_command("refresh", "; rm -rf /", args, {"AAPL"})
        assert argv is None and err == "unknown symbol"

    def test_symbol_actions_build_argv_without_a_shell(self):
        argv, err = webapp.desk_command("refresh", "AAPL", self.Args(), {"AAPL"})
        assert err is None
        assert argv[1:] == ["enrich.py", "--force-refresh", "--symbols", "AAPL",
                            "--cache", "ec"]
        argv, err = webapp.desk_command("thesis", "AAPL", self.Args(), {"AAPL"})
        assert err is None and argv[1:4] == ["thesis.py", "brief", "AAPL"]
        assert "--theses-dir" in argv and "th" in argv

    def test_refresh_needs_a_cache(self):
        class NoCache(self.Args):
            enrich_cache = None
        argv, err = webapp.desk_command("refresh", "AAPL", NoCache(), {"AAPL"})
        assert argv is None and "enrich-cache" in err

    def test_ratify_is_not_reachable_from_the_web(self):
        """FR9: conviction is asked of a human at the Gate, never clicked."""
        assert "ratify" not in webapp.DESK_ACTIONS
        for builder, _ in webapp.DESK_ACTIONS.values():
            if builder is None:
                continue
            argv = builder(self.Args(), "AAPL")
            assert "ratify" not in argv

    def test_monitor_run_carries_the_enrichment_cache(self):
        argv, err = webapp.desk_command("monitor-run", None, self.Args(), set())
        assert err is None and "--enrich-cache" in argv and "ec" in argv
