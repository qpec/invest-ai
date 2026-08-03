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
