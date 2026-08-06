"""The enrichment chain — fill-only-missing, provenance, PIT survival, guarded vendor.

Fully offline (R15): the EDGAR transport is a dict lookup, never a socket.
"""
from __future__ import annotations

import json

import pytest

import enrich
import pit


def entry(end, filed, val, start=None, form="10-K"):
    e = {"end": end, "filed": filed, "form": form, "val": val}
    if start:
        e["start"] = start
    return e


def payload(symbol="AAA", tags=None):
    return {"cik": None, "entityName": None, pit.SYMBOL_KEY: symbol,
            "facts": {"us-gaap": tags or {}}}


def concept(*entries, unit="USD"):
    return {"label": "x", "units": {unit: list(entries)}}


def fake_transport(responses):
    calls = []

    def transport(url):
        calls.append(url)
        for key, value in responses.items():
            if key in url:
                return json.dumps(value).encode()
        raise AssertionError(f"unexpected URL {url}")

    transport.calls = calls
    return transport


class TestMergePayload:
    def test_fills_only_missing_tags_and_stamps_provenance(self):
        base = payload(tags={"Revenues": concept(entry("2025-12-31", "2026-02-01", 100.0,
                                                       start="2025-01-01"))})
        extra = payload(tags={
            "Revenues": concept(entry("2025-12-31", "2026-02-01", 999.0,
                                      start="2025-01-01")),
            "LongTermDebtNoncurrent": concept(entry("2025-12-31", "2026-02-01", 50.0)),
        })
        added = enrich.merge_payload(base, extra)
        assert added == ["us-gaap:LongTermDebtNoncurrent"]
        # The export's own Revenues entry is untouched: a lower tier never overrides.
        revs = base["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        assert [e["val"] for e in revs] == [100.0]
        assert base[enrich.ENRICHMENT_KEY] == {
            "us-gaap:LongTermDebtNoncurrent": enrich.TIER_EDGAR}

    def test_new_namespace_is_created_not_dropped(self):
        base = payload()
        extra = {"facts": {"dei": {"EntityCommonStockSharesOutstanding":
                                   concept(entry("2025-12-31", "2026-02-01", 60.0),
                                           unit="shares")}}}
        added = enrich.merge_payload(base, extra)
        assert added == ["dei:EntityCommonStockSharesOutstanding"]
        assert "dei" in base["facts"]

    def test_pit_filter_still_applies_to_merged_entries(self):
        """The whole reason tier 2 merges FACTS rather than metrics: an entry filed after
        as_of must stay invisible, enriched or not."""
        base = payload(tags={"Revenues": concept(
            entry("2024-12-31", "2025-02-01", 100.0, start="2024-01-01"),
            entry("2025-12-31", "2026-02-01", 130.0, start="2025-01-01"))})
        extra = payload(tags={"GrossProfit": concept(
            entry("2024-12-31", "2025-02-01", 40.0, start="2024-01-01"),
            entry("2025-12-31", "2026-02-01", 60.0, start="2025-01-01"))})
        enrich.merge_payload(base, extra)
        bundle = pit.as_of_bundle(base, "AAA", None, "2025-06-30", {})
        income = (bundle.get("annual") or {}).get("income") or {}
        gp = income.get("gross_profit")
        years = gp if isinstance(gp, dict) else {}
        assert "2025-12-31" not in json.dumps(income), \
            "an entry filed 2026 leaked into an as-of-2025 bundle"


class TestFetchAndCache:
    def test_fetch_uses_cache_before_network(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "CIK0000000007.json").write_text(json.dumps({"cached": True}))
        transport = fake_transport({})
        got = enrich.fetch_companyfacts(7, transport=transport, cache_dir=cache)
        assert got == {"cached": True} and transport.calls == []

    def test_fetch_writes_cache_after_network(self, tmp_path):
        transport = fake_transport({"CIK0000000007": {"facts": {}}})
        enrich.fetch_companyfacts(7, transport=transport, cache_dir=tmp_path)
        assert (tmp_path / "CIK0000000007.json").exists()
        assert len(transport.calls) == 1

    def test_cik_map_shape(self):
        transport = fake_transport({"company_tickers":
                                    {"0": {"cik_str": 1334036, "ticker": "CROX",
                                           "title": "Crocs, Inc."}}})
        assert enrich.cik_map(transport) == {"CROX": 1334036}


class TestEnrichPayloads:
    def test_unknown_symbol_is_skipped_not_guessed(self):
        facts = {"AAA": payload()}
        log = []
        added = enrich.enrich_payloads(facts, ["ZZZ"], transport=fake_transport({}),
                                       ciks={}, log=log.append)
        assert added == {} and any("skipped, not guessed" in line for line in log)

    def test_one_dead_fetch_does_not_kill_the_sweep(self):
        facts = {"AAA": payload("AAA"), "BBB": payload("BBB")}

        def transport(url):
            if "0000000001" in url:
                raise OSError("connection reset")
            return json.dumps(payload(tags={
                "GrossProfit": concept(entry("2025-12-31", "2026-02-01", 1.0,
                                             start="2025-01-01"))})).encode()

        log = []
        added = enrich.enrich_payloads(facts, ["AAA", "BBB"], transport=transport,
                                       ciks={"AAA": 1, "BBB": 2}, log=log.append)
        assert "BBB" in added and "AAA" not in added
        assert any("stays un-enriched" in line for line in log)

    def test_vendor_tier_is_labelled_and_offline(self):
        """Tier 3 is display-only by construction. Injectable info source, so this test
        never opens a socket (R15) — the first cut called live yfinance, which was
        exactly the class of test this repo refuses."""
        info = {"totalDebt": 1_310e6, "totalCash": 170e6, "ebitda": 927e6,
                "grossMargins": 0.588}
        out = enrich.vendor_metrics("CROX", ticker_info=lambda s: info)
        assert out["net_debt_to_ebitda"]["v"] == 1.23
        assert out["gross_margin_pct"]["v"] == 58.8
        for item in out.values():
            assert item["source"] == enrich.TIER_VENDOR
            assert "never scored" in item["note"]

    def test_vendor_absence_is_an_empty_cherry(self):
        assert enrich.vendor_metrics("X", ticker_info=lambda s: {}) == {}

    def test_vendor_file_roundtrip(self, tmp_path):
        enrich.write_vendor(tmp_path, {"CROX": {"net_debt_to_ebitda": {
            "v": 1.23, "source": enrich.TIER_VENDOR, "note": "never scored"}}})
        assert enrich.load_vendor(tmp_path)["CROX"]["net_debt_to_ebitda"]["v"] == 1.23
        (tmp_path / enrich.VENDOR_FILE).write_text("{ corrupt")
        assert enrich.load_vendor(tmp_path) == {}

    def test_corrupt_ticker_cache_falls_through_to_fetch(self, tmp_path):
        """Review 2026-08-03: .exists() alone believed a truncated _tickers.json and
        poisoned every later run."""
        (tmp_path / "_tickers.json").write_text("{ truncated")
        transport = fake_transport({"company_tickers":
                                    {"0": {"cik_str": 7, "ticker": "AAA",
                                           "title": "Alpha"}}})
        assert enrich.cik_map_cached(tmp_path, transport) == {"AAA": 7}
        assert len(transport.calls) == 1
        # and the rewrite healed the cache
        assert enrich.cik_map_cached(tmp_path, fake_transport({})) == {"AAA": 7}


class TestConsumedTagsAndPrune:
    def test_consumed_tags_cover_every_pit_table(self):
        """Introspection, not a copy: every chain in every pit concept table must be in
        the selection — a new chain that is not would be silently unfetchable."""
        import secsv
        keep = enrich.consumed_tags()
        for table in (pit._INCOME_CONCEPTS, pit._CASHFLOW_CONCEPTS,
                      pit._BALANCE_CONCEPTS, pit._SUPPLEMENT_FLOW_CONCEPTS,
                      pit._SUPPLEMENT_POINT_CONCEPTS, pit._DISCLOSURE_CONCEPTS):
            for chain in table.values():
                for tag in chain:
                    assert tag in keep["us-gaap"], tag
        for tag in secsv._PIT_EXTRA_INSTANT_TAGS:
            assert tag in keep["us-gaap"], tag
        assert pit._SHARES_TAG in keep["dei"]

    def test_prune_keeps_consumed_drops_the_rest(self):
        raw = {"cik": 99, "entityName": "Alpha", "_fetched": "2026-08-05",
               "facts": {"us-gaap": {"Revenues": concept(entry("2025-12-31",
                                                               "2026-02-01", 1.0)),
                                     "SomeExoticFootnoteTag": concept(
                                         entry("2025-12-31", "2026-02-01", 2.0))},
                         "dei": {pit._SHARES_TAG: concept(
                             entry("2025-12-31", "2026-02-01", 10.0), unit="shares")},
                         "ifrs-full": {"Revenue": concept(
                             entry("2025-12-31", "2026-02-01", 3.0))}}}
        pruned = enrich.prune_payload(raw)
        assert pruned["cik"] == 99 and pruned["_fetched"] == "2026-08-05"
        assert "Revenues" in pruned["facts"]["us-gaap"]
        assert "SomeExoticFootnoteTag" not in pruned["facts"]["us-gaap"]
        assert "ifrs-full" not in pruned["facts"]          # pit never reads it
        assert pit._SHARES_TAG in pruned["facts"]["dei"]


class TestBootstrap:
    def _cached_facts(self, tmp_path, cik=7):
        raw = {"cik": cik, "entityName": "Alpha",
               "facts": {"us-gaap": {"Revenues": concept(
                   entry("2025-12-31", "2026-02-01", 100.0, start="2025-01-01"))}}}
        (tmp_path / f"CIK{cik:010d}.json").write_text(json.dumps(raw))
        return raw

    def test_bootstrap_creates_payload_with_full_edgar_ledger(self, tmp_path):
        self._cached_facts(tmp_path)
        facts = {}
        made = enrich.bootstrap_payloads(facts, ["aaa"], cache_dir=tmp_path,
                                         ciks={"AAA": 7}, cache_only=True)
        assert made == {"AAA": 1}
        assert facts["AAA"][pit.SYMBOL_KEY] == "AAA"
        assert facts["AAA"][enrich.ENRICHMENT_KEY] == {
            "us-gaap:Revenues": enrich.TIER_EDGAR}

    def test_bootstrap_is_additive_only(self, tmp_path):
        """The frozen decision layer: a symbol the export knows is NEVER touched."""
        self._cached_facts(tmp_path)
        original = payload("AAA", tags={"Revenues": concept(
            entry("2025-12-31", "2026-02-01", 555.0, start="2025-01-01"))})
        facts = {"AAA": original}
        before = json.dumps(original, sort_keys=True)
        made = enrich.bootstrap_payloads(facts, ["AAA"], cache_dir=tmp_path,
                                         ciks={"AAA": 7}, cache_only=True)
        assert made == {}
        assert json.dumps(facts["AAA"], sort_keys=True) == before

    def test_cache_only_never_touches_the_network(self, tmp_path):
        def exploding_transport(url):
            raise AssertionError(f"network touched: {url}")
        facts = {}
        made = enrich.bootstrap_payloads(facts, ["BBB"], cache_dir=tmp_path,
                                         ciks={"BBB": 8}, cache_only=True,
                                         transport=exploding_transport)
        assert made == {} and facts == {}   # pending, not guessed

    def test_unknown_symbol_is_skipped_not_guessed(self, tmp_path):
        facts = {}
        made = enrich.bootstrap_payloads(facts, ["ZZZ"], cache_dir=tmp_path,
                                         ciks={}, cache_only=True)
        assert made == {} and facts == {}


class TestRollingRefresh:
    def test_priority_first_then_stalest_and_budget_never_cuts_priority(self, tmp_path):
        import os
        import time as _time
        ciks = {"CRX": 1, "OLD": 2, "NEW": 3, "MID": 4}
        # OLD has the oldest cache file, MID newer, NEW has none (infinitely stale)
        for sym, age_days in (("OLD", 30), ("MID", 1)):
            path = tmp_path / f"CIK{ciks[sym]:010d}.json"
            path.write_text(json.dumps({enrich.SCHEMA_KEY: enrich.tag_schema_id()}))
            stamp = _time.time() - age_days * 86400
            os.utime(path, (stamp, stamp))
        (tmp_path / "_tickers.json").write_text(json.dumps(ciks))
        fetched = []

        def transport(url):
            fetched.append(url)
            return json.dumps({"cik": 0, "facts": {}}).encode()

        summary = enrich.rolling_refresh(
            tmp_path, ["OLD", "NEW", "MID", "CRX", "NOPE"],
            priority=["CRX"], budget=3, transport=transport)
        # plan: CRX (priority) + NEW (no file) + OLD (oldest) — MID over budget,
        # NOPE not a filer
        assert summary["planned"] == 3 and summary["priority"] == 1
        assert summary["not_sec_filers"] == 1
        order = [int(u.split("CIK")[1][:10]) for u in fetched]
        assert order == [ciks["CRX"], ciks["NEW"], ciks["OLD"]]

    def test_thesis_symbols_reads_both_artifact_shapes(self, tmp_path):
        (tmp_path / "committed").mkdir()
        (tmp_path / "committed" / "aaa.json").write_text("{}")
        (tmp_path / "drafts" / "BBB").mkdir(parents=True)
        (tmp_path / "drafts" / "monitor-2026-08-09").mkdir()   # the spool, not a thesis
        assert enrich.thesis_symbols(tmp_path) == ["AAA", "BBB"]


class TestPruneReviewRegressions:
    """Preflight review 2026-08-05: the three ways the first prune changed numbers."""

    def test_restatement_on_a_non_annual_form_survives(self):
        """GOOG FY2013 OCF (reproduced live): the 8-K restatement is the latest-filed
        winner and must not lose to a form-filtered 10-K value."""
        raw = {"facts": {"us-gaap": {"NetCashProvidedByUsedInOperatingActivities": {
            "units": {"USD": [
                entry("2013-12-31", "2016-02-11", 18659.0, start="2013-01-01",
                      form="10-K"),
                entry("2013-12-31", "2016-05-03", 19140.0, start="2013-01-01",
                      form="8-K"),
            ]}}}}}
        got = enrich.prune_payload(raw)["facts"]["us-gaap"][
            "NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"]
        assert [e["val"] for e in got] == [19140.0]

    def test_annual_series_keep_full_depth(self):
        """The growth anchors read the OLDEST annual point — no annual horizon."""
        raw = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            entry("2009-12-31", "2010-02-11", 1.0, start="2009-01-01", form="10-K"),
            entry("2024-12-31", "2025-02-11", 9.0, start="2024-01-01", form="10-K"),
        ]}}}}}
        got = enrich.prune_payload(raw)["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        assert [e["end"] for e in got] == ["2009-12-31", "2024-12-31"]

    def test_old_quarterlies_are_cut_but_old_annual_instants_kept(self):
        raw = {"facts": {"us-gaap": {"Assets": {"units": {"USD": [
            entry("2012-12-31", "2013-02-11", 5.0, form="10-K"),      # annual instant
            entry("2012-03-31", "2012-05-01", 4.0, form="10-Q"),      # ancient quarterly
        ]}}}}}
        got = enrich.prune_payload(raw)["facts"]["us-gaap"]["Assets"]["units"]["USD"]
        assert [e["end"] for e in got] == ["2012-12-31"]

    def test_equal_filed_tie_matches_latest_filed(self):
        """>= tie-break: among equal filed dates the LATER list entry wins, exactly as
        pit._latest_filed resolves it."""
        raw = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            entry("2024-12-31", "2025-02-11", 1.0, start="2024-01-01", form="10-K"),
            entry("2024-12-31", "2025-02-11", 2.0, start="2024-01-01", form="10-K/A"),
        ]}}}}}
        got = enrich.prune_payload(raw)["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        assert [e["val"] for e in got] == [2.0]

    def test_dei_shares_exempt_from_horizon_and_dedupe(self):
        """shares_series groups raw entries per filed date to DETECT inconsistent
        filings (AAPL's 2010-01-25 double report) and shares_fallback needs the last
        observation however old (BRK) — the tag is slimmed, never cut."""
        raw = {"facts": {"dei": {pit._SHARES_TAG: {"units": {"shares": [
            entry("2009-10-16", "2010-01-25", 900.0, form="10-K/A"),
            entry("2010-01-15", "2010-01-25", 906.0, form="10-Q"),
        ]}}}}}
        got = enrich.prune_payload(raw)["facts"]["dei"][pit._SHARES_TAG]["units"]["shares"]
        assert [e["val"] for e in got] == [900.0, 906.0]


class TestBootstrapBundles:
    def test_streaming_bundle_and_pending_count(self, tmp_path):
        raw = {"cik": 7, "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                entry("2024-12-31", "2025-02-11", 100.0, start="2024-01-01",
                      form="10-K")]}},
            "Assets": {"units": {"USD": [
                entry("2024-12-31", "2025-02-11", 500.0, form="10-K")]}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
                entry("2024-12-31", "2025-02-11", 30.0, start="2024-01-01",
                      form="10-K")]}},
        }}}
        (tmp_path / "CIK0000000007.json").write_text(json.dumps(raw))
        bundles, pending = enrich.bootstrap_bundles(
            ["AAA", "BBB", "NOPE"], cache_dir=tmp_path,
            ciks={"AAA": 7, "BBB": 8}, as_of="2026-08-05")
        assert pending == 1                      # BBB awaits a fetch; NOPE not a filer
        assert [b["symbol"] for b in bundles] == ["AAA"]
        assert bundles[0]["annual"]["income"]["2024-12-31"]["Total Revenue"] == 100.0


class TestSecMerge:
    def _run(self, tmp_path, listed_rows, existing_rows):
        import csv
        base = tmp_path / "base.csv"
        cols = ["symbol", "name", "sector", "industry", "country", "market_cap",
                "exchange", "currency"]
        with base.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for sym in existing_rows:
                w.writerow({**{c: "" for c in cols}, "symbol": sym})
        import universe
        out = tmp_path / "out.csv"
        payload = {"fields": ["cik", "name", "ticker", "exchange"],
                   "data": listed_rows}
        universe.sec_merge(base, out,
                           transport=lambda url: json.dumps(payload).encode())
        with out.open(newline="") as fh:
            return [r["symbol"] for r in csv.DictReader(fh)]

    def test_sibling_class_of_a_curated_business_is_blocked(self, tmp_path):
        got = self._run(tmp_path,
                        [[1652044, "Alphabet", "GOOGL", "Nasdaq"],
                         [1652044, "Alphabet", "GOOG", "Nasdaq"]],
                        existing_rows=["GOOG"])
        assert got == ["GOOG"]                   # GOOGL never doubles the business

    def test_canonical_prefers_plain_shortest_line(self, tmp_path):
        got = self._run(tmp_path,
                        [[10, "OABI Co Warrant", "OABIW", "Nasdaq"],
                         [10, "OABI Co", "OABI", "Nasdaq"],
                         [11, "Brown-Forman A", "BF-A", "NYSE"],
                         [11, "Brown-Forman B", "BF-B", "NYSE"],
                         [12, "Entergy Texas Pref", "ETI-P", "NYSE"],
                         [13, "ETF Thing", "ZZZ", "NYSE Arca"]],
                        existing_rows=[])
        # OABI over its warrant; a class line (BF-A, first in file) when no plain
        # line exists; the preferred-only filer and the ETF venue dropped whole.
        assert got == ["OABI", "BF-A"]


class TestCacheSchemaStamp:
    """2026-08-05: widening a concept chain leaves every older cached payload silently
    missing the new tags — and a missing tag reads as 'the filer does not report this'.
    Comcast came out debt-free that way."""

    def test_a_payload_from_an_older_schema_is_refetched_first(self, tmp_path):
        ciks = {"OLD": 1, "CUR": 2}
        (tmp_path / "_tickers.json").write_text(json.dumps(ciks))
        (tmp_path / "CIK0000000001.json").write_text(json.dumps({"_tag_schema": "deadbeef"}))
        (tmp_path / "CIK0000000002.json").write_text(
            json.dumps({enrich.SCHEMA_KEY: enrich.tag_schema_id()}))
        fetched = []

        def transport(url):
            fetched.append(url)
            return json.dumps({"cik": 0, "facts": {}}).encode()

        enrich.rolling_refresh(tmp_path, ["CUR", "OLD"], budget=1, transport=transport)
        assert [int(u.split("CIK")[1][:10]) for u in fetched] == [1]   # the outdated one
