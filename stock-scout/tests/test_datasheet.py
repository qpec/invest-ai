"""Offline tests for datasheet.py (spec §5.7, §3.3, §3.5): synthetic grades JSON
(one graded name with flags+MoS+Buffett+Owner's Scorecard, one vetoed) + cache entry +
Stage-2 files; assert the HTML leads with the scorecard block, renders every ramp from
scorecard.ANCHORS, carries the whole pre-existing evidence chain, embeds BOTH JSON-island
recomputes, references no external asset, and that the Stage-2 date-fallback picks the
newest file ≤ run date. No network, no real caches.

The last section covers the inversion layer in the audit (docs/INVERSION-DESIGN.md §5):
the verdict, the failure modes, every probe with its value and severity, and the coverage
line NAMING the probes that were not measured — plus the case that is normal rather than
degraded, a grades JSON with no verdicts at all."""
from __future__ import annotations

import json
import re

import pytest

import datasheet
import scorecard

RUN_DATE = "2026-07-30"

# Legs → pillar means: v=90.0, q=(88+64+85)/3=79.0, g=72.5, d=80.0, m=68.5
# composite = .25*90 + .25*79 + .20*72.5 + .15*80 + .15*68.5 = 79.025 (§4.6)
LEGS = {
    "v_yield": {"raw": 0.082, "percentile": 90.0, "cohort_n": 12, "score": 90.0,
                "note": "owner-FCF-yield op eigen EV"},
    "q_roic": {"raw": 45.3, "percentile": 88.0, "cohort_n": 12, "score": 88.0, "note": ""},
    "q_gm": {"raw": 62.0, "percentile": 80.0, "cohort_n": 12, "score": 64.0,
             "note": "niveau × stabiliteit"},
    "q_ofcf_margin": {"raw": 30.1, "percentile": 85.0, "cohort_n": 12, "score": 85.0, "note": ""},
    "g_revenue": {"raw": 12.4, "percentile": 75.0, "cohort_n": 12, "score": 75.0, "note": ""},
    "g_ps_ofcf": {"raw": 15.0, "percentile": 70.0, "cohort_n": 12, "score": 70.0, "note": ""},
    "d_net_debt": {"raw": -0.5, "percentile": 80.0, "cohort_n": 12, "score": 80.0, "note": ""},
    "d_self_funding": {"raw": True, "percentile": None, "cohort_n": None, "score": 100.0,
                       "note": "owner-FCF TTM > 0"},
    "d_sbc": {"raw": 4.2, "percentile": 60.0, "cohort_n": 12, "score": 60.0, "note": ""},
    "m_shares": {"raw": -1.2, "percentile": 82.0, "cohort_n": 12, "score": 82.0, "note": ""},
    "m_accruals": {"raw": 2.0, "percentile": 55.0, "cohort_n": 12, "score": 55.0, "note": ""},
}
COMPOSITE = 79.025

# One raw value per scorecard anchor; capital-returned is deliberately absent so the
# fixture also exercises §4.2 — a shrinking denominator, never a silent zero.
SC_VALUES = {
    "roic": 45.3, "gross_margin": 62.0, "gross_margin_cv": 0.04,
    "owner_fcf_margin": 30.1, "revenue_growth": 12.4, "owner_fcf_yield": 0.082,
    "margin_of_safety": 0.214, "net_debt_ebitda": -0.5, "self_funding": 1.0,
    "sbc": 4.2, "current_ratio": 1.5, "share_count_trend": -1.2, "accruals": 2.0,
    "capital_returned": None,
}
CAPITAL_REASON = ("no dividend or buyback row in the newest annual cash-flow statement "
                  "(the EDGAR/PIT path carries neither)")


def _ramp(value: float, floor: float, target: float, points: float) -> float:
    """The design §2 rule, spelled out HERE: the fixture must not inherit its numbers
    from the implementation the datasheet is supposed to render faithfully."""
    frac = (value - floor) / (target - floor)
    return round(max(0.0, min(1.0, frac)) * points, 1)


def _scorecard_card() -> dict:
    """A §5 card in exactly the shape scorecard.scorecard() emits (§3.3)."""
    metrics, blocks, missing, scored = {}, {}, [], []
    for mid, a in scorecard.ANCHORS.items():
        block = blocks.setdefault(a["block"], {"points": 0.0, "max": 0, "metrics": []})
        value = SC_VALUES[mid]
        if value is None:
            metrics[mid] = {"value": None, "points": None, "max": a["points"],
                            "pct": None,
                            "detail": f"{a['label']}: not computable — {CAPITAL_REASON} "
                                      f"(§4.2)"}
            missing.append({"metric": mid, "label": a["label"], "block": a["block"],
                            "points": a["points"], "reason": CAPITAL_REASON})
            continue
        pts = _ramp(value, a["floor"], a["target"], a["points"])
        metrics[mid] = {"value": value, "points": pts, "max": a["points"],
                        "pct": round(100.0 * pts / a["points"]),
                        "detail": f"{a['label']} -> {pts}/{a['points']} pts"}
        block["points"] = round(block["points"] + pts, 1)
        block["max"] += a["points"]
        block["metrics"].append(mid)
        scored.append(mid)
    score = round(sum(b["points"] for b in blocks.values()), 1)
    available = sum(b["max"] for b in blocks.values())
    pct = round(100.0 * score / available)
    entry = next(e for e in scorecard.BANDS
                 if e["floor"] is not None and pct >= e["floor"])
    return {
        "score": score, "available_max": available, "pct": pct, "band": entry["band"],
        "band_meaning": entry["meaning"], "blocks": blocks, "metrics": metrics,
        "why": {"strongest": {"metric": "net_debt_ebitda", "label": "net debt/EBITDA",
                              "value": -0.5, "points": 10.0, "max": 10, "pct": 100,
                              "sentence": "carried by net debt/EBITDA at -0.50 (10.0/10)"},
                "weakest": {"metric": "revenue_growth", "label": "revenue growth",
                            "value": 12.4, "points": 4.1, "max": 5, "pct": 83,
                            "sentence": "held back by revenue growth at +12.4%/yr "
                                        "(4.1/5)"}},
        "consensus": {"green": 3, "of": 3,
                      "lenses": {"scorecard": True, "margin_of_safety": True,
                                 "buffett": True},
                      "label": "3 of 3 — all three lenses agree",
                      "evidence": {"scorecard": f"scorecard {pct}% (>= 60%)",
                                   "margin_of_safety": "margin of safety +21% (> 0%)",
                                   "buffett": "Buffett 11/13 (>= 9)"}},
        "coverage": {"available_max": available, "full_max": 100, "scored": scored,
                     "missing": missing, "missing_points": 3},
        "veto": {"vetoed": False, "reason": "", "penalty": 0},
        "notes": ["1 metric(s) not computable — scored out of 97 of 100 possible "
                  "points (§4.2).",
                  "Differences under 5 points are not meaningful (§4.4)."],
    }


SCORECARD = _scorecard_card()


def _grades() -> dict:
    return {
        "run_date": RUN_DATE, "version": "v2.3+v3", "universe": 2, "graded": 1,
        "vetoed": 1, "insufficient": 0,
        "names": [
            {"symbol": "TEST", "name": "Test Compounder Inc.",
             "sector": "Information Technology", "industry": "Software", "tier": "Core",
             "grade": "B", "composite": COMPOSITE, "quality_score": 76.0,
             "pillars": {"v": 90.0, "q": 79.0, "g": 72.5, "d": 80.0, "m": 68.5},
             "legs": LEGS,
             "veto": {"vetoed": False, "reason": "", "penalty": 0},
             "flags": [{"code": "EV_GAP", "message": "eigen EV wijkt 19.1% af van Yahoo-EV"},
                       {"code": "FLOAT_ROIC", "message": "vooruitontvangen omzet 34% van omzet"}],
             "ev": {"own": 8.9e9, "yahoo": 10.6e9, "gap_pct": 19.1},
             "ttm": {"quarters": 4, "through": "2026-06-30", "basis": "quarterly"},
             "mos": {"intrinsic_value": 10.2e9, "market_cap": 8.4e9, "mos_pct": 0.214,
                     "wacc": 0.085, "growth": 0.124, "base_fcf": 6.4e8},
             "buffett": {"score": 11, "max": 13, "items": [
                 {"name": "ROE > 15%", "points": 2, "max": 2, "pass": True,
                  "detail": "ROE 21.3%"},
                 {"name": "D/E < 0.5", "points": 2, "max": 2, "pass": True,
                  "detail": "D/E 0.18"},
                 {"name": "Winstconsistentie", "points": 0, "max": 3, "pass": False,
                  "detail": "NI daalde in 2024"}]},
             "scorecard": json.loads(json.dumps(SCORECARD))},
            {"symbol": "BADCO", "name": "Bad Leverage Co.",
             "sector": "Health Care", "industry": "Health Care Technology", "tier": "Core",
             "grade": "VETOED", "composite": None, "quality_score": None,
             "pillars": {"v": None, "q": None, "g": None, "d": None, "m": None},
             "legs": {},
             "veto": {"vetoed": True, "penalty": 0,
                      "reason": "leverage veto: net debt/EBITDA above the §2 floor"},
             "flags": [], "ev": None,
             "ttm": {"quarters": 0, "through": None, "basis": "annual"},
             "mos": None, "buffett": None, "scorecard": None},
        ],
        "portfolio": {"positions": [{"symbol": "TEST", "weight": 0.10,
                                     "conviction": COMPOSITE}],
                      "cash": 0.90, "clamps": ["TEST: 5.3% -> 10% cap"]},
        "formation": {"as_of": RUN_DATE, "quarter": "2026Q3", "slots": 15,
                      "squad": [{"symbol": "TEST", "since": "2026Q2",
                                 "entered_date": "2026-04-06", "quality_rank": 1,
                                 "streak": 2}],
                      "bench": [], "transfers": []},
    }


def _cache_entry() -> dict:
    annual_cf = {
        "2024-12-31": {"Operating Cash Flow": 2.6e8, "Capital Expenditure": -4.5e7,
                       "Stock Based Compensation": 2.8e7,
                       "Depreciation And Amortization": 5.0e7},
        "2025-12-31": {"Operating Cash Flow": 2.8e8, "Capital Expenditure": -4.0e7,
                       "Stock Based Compensation": 3.0e7,
                       "Depreciation And Amortization": 5.2e7},
    }
    q_cf = {"2025-09-30": {"Operating Cash Flow": 7.0e7, "Capital Expenditure": -1.0e7,
                            "Stock Based Compensation": 8.0e6},
            "2025-12-31": {"Operating Cash Flow": 7.2e7, "Capital Expenditure": -1.1e7,
                           "Stock Based Compensation": 8.0e6},
            "2026-03-31": {"Operating Cash Flow": 7.4e7, "Capital Expenditure": -0.9e7,
                           "Stock Based Compensation": 8.5e6,
                           "Provision For Doubtful Accounts": 2.0e6},
            "2026-06-30": {"Operating Cash Flow": 7.6e7, "Capital Expenditure": -1.0e7,
                           "Stock Based Compensation": 8.5e6}}
    return {
        "ticker": "TEST", "fetched_at": "2026-07-30T10:00:00+00:00",
        "meta": {"name": "Test Compounder Inc.", "sector": "Information Technology",
                 "industry": "Software", "country": "United States"},
        "currency": "USD", "price": {"close": 123.4, "date": "2026-07-30"},
        "fast_info": {"last_price": 123.4, "market_cap": 8.4e9, "shares": 6.8e7,
                      "currency": "USD"},
        "shares": {"2025-07-01": 6.9e7, "2026-07-01": 6.8e7},
        "annual": {
            "income": {"2025-12-31": {"Operating Revenue": 1.1e9, "EBITDA": 3.2e8,
                                      "EBIT": 2.6e8, "Net Income": 2.1e8,
                                      "Gross Profit": 6.8e8, "Operating Income": 2.6e8}},
            "balance": {"2025-12-31": {"Total Debt": 2.0e8,
                                       "Cash And Cash Equivalents": 7.0e8,
                                       "Working Capital": 3.0e8, "Total Assets": 2.0e9,
                                       "Current Assets": 9.0e8,
                                       "Current Liabilities": 6.0e8,
                                       "Stockholders Equity": 1.1e9}},
            "cashflow": annual_cf,
        },
        "quarterly": {"cashflow": q_cf},
    }


def _stage2(date: str, verdict: str, marker: str) -> dict:
    return {"run_date": date,
            "analyses": {"TEST": {"verdict": verdict, "analysis": marker,
                                  "sources": [{"title": "Test Q2 2026", "url": None}]}}}


@pytest.fixture()
def workdir(tmp_path):
    reports = tmp_path / "reports"
    cache = tmp_path / "cache"
    data = tmp_path / "data"
    for d in (reports, cache, data):
        d.mkdir()
    grades_path = reports / f"scout-grades-{RUN_DATE}.json"
    grades_path.write_text(json.dumps(_grades()), encoding="utf-8")
    (cache / "TEST.json").write_text(json.dumps(_cache_entry()), encoding="utf-8")
    # Three Stage-2 files: older, newest ≤ run date, and one AFTER the run date
    # (must be ignored per §3.5). No exact run-date file → fallback must pick 07-29.
    (data / "stage2-2026-07-25.json").write_text(
        json.dumps(_stage2("2026-07-25", "Kandidaat", "OUDERE-LAAG")), encoding="utf-8")
    (data / "stage2-2026-07-29.json").write_text(
        json.dumps(_stage2("2026-07-29", "Sterke kandidaat", "NIEUWSTE-LAAG-MARKER")),
        encoding="utf-8")
    (data / "stage2-2026-08-09.json").write_text(
        json.dumps(_stage2("2026-08-09", "Terughoudend", "TOEKOMST-MARKER")),
        encoding="utf-8")
    return {"grades": grades_path, "cache": cache, "data": data, "tmp": tmp_path}


# ------------------------------------------------------------- stage-2 resolution

def test_find_stage2_fallback_picks_newest_lte_run_date(workdir):
    p = datasheet.find_stage2(workdir["data"], RUN_DATE)
    assert p is not None and p.name == "stage2-2026-07-29.json"


def test_find_stage2_prefers_exact_run_date_match(workdir):
    exact = workdir["data"] / f"stage2-{RUN_DATE}.json"
    exact.write_text(json.dumps(_stage2(RUN_DATE, "Kandidaat", "EXACT")), encoding="utf-8")
    assert datasheet.find_stage2(workdir["data"], RUN_DATE) == exact


def test_find_stage2_none_when_all_files_are_future(tmp_path):
    (tmp_path / "stage2-2027-01-01.json").write_text("{}", encoding="utf-8")
    assert datasheet.find_stage2(tmp_path, RUN_DATE) is None


# ------------------------------------------------------------- full build

@pytest.fixture()
def built_html(workdir):
    out = datasheet.build(workdir["grades"], cache_dir=workdir["cache"],
                          stage2_dir=workdir["data"], top=10)
    assert out.name == f"datasheet-{RUN_DATE}.html"
    return out.read_text(encoding="utf-8")


def test_html_contains_all_legs(built_html):
    for leg_id in ("v_yield", "q_roic", "q_gm", "q_ofcf_margin", "g_revenue", "g_ps_ofcf",
                   "d_net_debt", "d_self_funding", "d_sbc", "m_shares", "m_accruals"):
        assert leg_id in built_html


def test_html_contains_flags_with_messages(built_html):
    assert "EV_GAP" in built_html
    assert "FLOAT_ROIC" in built_html
    assert "eigen EV wijkt 19.1% af van Yahoo-EV" in built_html
    assert "float-gedreven" in built_html          # the NL flag explanation (msg 19)


def test_html_contains_stage2_verdict_from_fallback_file(built_html):
    assert "Sterke kandidaat" in built_html
    assert "NIEUWSTE-LAAG-MARKER" in built_html
    assert "TOEKOMST-MARKER" not in built_html     # a future-dated layer is never used
    assert "OUDERE-LAAG" not in built_html         # the older layer loses to 07-29


def test_html_header_counts_and_veto_breakdown(built_html):
    assert "leverage veto" in built_html           # veto breakdown in the header
    assert "Alles uitklappen" in built_html
    assert "De Formatie 2026Q3" in built_html


def test_html_embeds_json_island_with_real_scores(built_html):
    m = re.search(r'<script type="application/json" id="scout-data">(.*?)</script>',
                  built_html, re.S)
    assert m, "JSON island missing"
    island = json.loads(m.group(1))
    assert island["weights"] == {"v": 0.25, "q": 0.25, "g": 0.20, "d": 0.15, "m": 0.15}
    cards = {c["symbol"]: c for c in island["cards"]}
    assert cards["TEST"]["composite"] == pytest.approx(COMPOSITE)
    assert cards["TEST"]["legs"]["v_yield"] == pytest.approx(90.0)
    assert "BADCO" not in cards                    # vetoed names are never ranked (§4.6)
    # The island really feeds the recompute: pillar means × weights + penalty == composite.
    recomputed = sum(island["weights"][p] * v for p, v in
                     {"v": 90.0, "q": 79.0, "g": 72.5, "d": 80.0, "m": 68.5}.items())
    assert recomputed == pytest.approx(COMPOSITE, abs=datasheet.RECHECK_TOLERANCE)


def test_html_recompute_js_present_not_baked(built_html):
    assert "recomputeComposite" in built_html      # genuine client-side re-derivation
    assert "komt overeen" in built_html
    assert "afwijking" in built_html
    # The verdict is rendered by JS, never baked into the static HTML:
    assert "✓ komt overeen" not in built_html.split("<script>")[0]


def test_html_is_self_contained_no_external_assets(built_html):
    lower = built_html.lower()
    assert "<link" not in lower
    assert "<script src" not in lower
    assert "<img" not in lower
    assert "url(http" not in lower
    assert 'src="http' not in lower and "src='http" not in lower
    assert "@import" not in lower
    # Fixture has no source URLs at all, so the page must carry zero http(s) references.
    assert "http://" not in lower and "https://" not in lower


def test_html_first_card_open_and_evidence_tables(built_html):
    assert re.search(r"<details class='card' open>", built_html)
    assert "Owner-FCF per periode" in built_html
    assert "Onderhouds-proxy" in built_html        # OCF − min(|CapEx|, D&A) − SBC build-up
    assert "Operating Revenue ✓" in built_html     # matched fallback label (§4.1)
    assert "fast_info-snapshot" in built_html
    assert "Buffett-checklist" in built_html
    assert "Veiligheidsmarge" in built_html        # MoS shadow block (§4.8)
    assert "prefers-color-scheme" in built_html    # light+dark theme


# ------------------------------------------- the Owner's Scorecard block (design §5)

def _card_html(doc: str, symbol: str = "TEST") -> str:
    """The body of one card, from its summary to the end of the card element."""
    part = doc.split(f"<b>1. {symbol}</b>", 1)[1]
    return part.split("</details><details class='card'", 1)[0]


def test_scorecard_is_the_top_block_of_the_card(built_html):
    card = _card_html(built_html)
    assert "Owner's Scorecard — absolute punten" in card
    sc_at = card.index("Owner's Scorecard")
    assert sc_at < card.index("Stage-2-analyse")          # above the Stage-2 layer...
    assert sc_at < card.index("Score-opbouw per leg")     # ...and the percentile build-up
    # Headline: pct/100 + band + the band's plain-language meaning (§5).
    assert f"<span class='sc-score'>{SCORECARD['pct']}</span>" in card
    assert "<span class='sc-max'>/100</span>" in card
    assert f"<span class='sc-band'>{SCORECARD['band']}</span>" in card
    assert SCORECARD["band_meaning"] in card
    # ...and the collapsed summary leads with it too, with the composite demoted.
    assert f"<b>{SCORECARD['pct']}/100</b> · {SCORECARD['band']}" in card
    assert "rang in sector: B 79.0" in card


def test_scorecard_block_shows_four_blocks_why_consensus_and_coverage(built_html):
    card = _card_html(built_html)
    for _, label, question in datasheet.BLOCK_LABELS:
        assert label in card and question in card
    quality = SCORECARD["blocks"]["quality"]
    assert f"{quality['points']:g}/{quality['max']}" in card       # e.g. 29/35
    assert "class='bar'" in card                                   # the block bars
    assert SCORECARD["why"]["strongest"]["sentence"] in card
    assert SCORECARD["why"]["weakest"]["sentence"] in card
    assert "Consensus 3/3" in card and "all three lenses agree" in card
    for lens, note in SCORECARD["consensus"]["evidence"].items():
        assert datasheet.LENS_LABELS[lens] in card
        assert datasheet._e(note) in card              # ">= 60%" is escaped, not dropped
    # Coverage names the metric that was NOT computable, and why (§4.2).
    assert "97 van 100" in card
    assert "capital returned / owner-FCF" in card
    assert CAPITAL_REASON in card
    assert "geen stille nul" in card


def test_every_metric_row_shows_value_ramp_and_points(built_html):
    card = _card_html(built_html)
    for mid, anchor in scorecard.ANCHORS.items():
        assert anchor["label"] in card and mid in card
        assert datasheet._ramp_text(mid) in card
    assert "0 bij 5.00% · vol bij 25.00%" in card           # ROIC's ramp, in ROIC's unit
    assert "45.30%" in card                                 # the raw value with its unit
    assert f"<b>{SCORECARD['metrics']['roic']['points']:g}</b>/12" in card
    # An unavailable metric keeps its row, its ramp and its reason — never a silent 0.
    assert "0 bij 0.000 · vol bij 0.500" in card


def test_ramps_are_rendered_from_anchors_not_hardcoded(workdir, tmp_path, monkeypatch):
    monkeypatch.setitem(datasheet.ANCHORS["roic"], "floor", 7.5)
    doc = datasheet.build(workdir["grades"], cache_dir=None, top=10,
                          out=tmp_path / "reanchored.html").read_text(encoding="utf-8")
    assert "0 bij 7.50% · vol bij 25.00%" in doc            # the page follows the table
    assert "0 bij 5.00% · vol bij 25.00%" not in doc


def test_anchor_provenance_table_is_rendered_once_from_anchors(built_html):
    assert f"{len(scorecard.ANCHORS)} metrieken, 100 punten" in built_html
    for mid in ("roic", "net_debt_ebitda", "share_count_trend"):
        assert datasheet._e(scorecard.ANCHORS[mid]["provenance"]) in built_html
    assert "Verschillen onder 5 punten zijn niet betekenisvol" in built_html


def test_island_carries_the_scorecard_for_an_independent_recompute(built_html):
    m = re.search(r'<script type="application/json" id="scout-data">(.*?)</script>',
                  built_html, re.S)
    island = json.loads(m.group(1))
    sc = {c["symbol"]: c["scorecard"] for c in island["cards"]}["TEST"]
    assert sc["score"] == SCORECARD["score"] and sc["pct"] == SCORECARD["pct"]
    # The island really feeds the recompute: block sums, available max and total all
    # re-derive from the per-metric points, and each point re-derives from its own ramp.
    blocks, total, available = {}, 0.0, 0
    for mid, metric in sc["metrics"].items():
        if metric["points"] is None:
            continue
        assert metric["floor"] == scorecard.ANCHORS[mid]["floor"]
        assert metric["points"] == pytest.approx(
            _ramp(metric["value"], metric["floor"], metric["target"], metric["max"]),
            abs=datasheet.RECHECK_TOLERANCE)
        blocks[metric["block"]] = blocks.get(metric["block"], 0.0) + metric["points"]
        total += metric["points"]
        available += metric["max"]
    for block, points in blocks.items():
        assert points == pytest.approx(sc["blocks"][block]["points"],
                                       abs=datasheet.RECHECK_TOLERANCE)
    assert total == pytest.approx(sc["score"], abs=datasheet.RECHECK_TOLERANCE)
    assert available == sc["available_max"]


def test_scorecard_recompute_js_present_not_baked(built_html):
    assert "recomputeScorecard" in built_html and "checkScorecard" in built_html
    assert "id='sc-recheck-TEST'" in built_html
    static = built_html.split("<script>")[0]
    assert "✓ komt overeen" not in static           # the verdict is JS-rendered, per card
    assert "JavaScript vereist" in static


def test_a_no_price_card_never_renders_as_a_verdict(workdir, tmp_path):
    """§4.1 on the datasheet: the literal NO PRICE band, the disclaimer, points out of
    what was available — and nowhere an x/100 headline."""
    grades = _grades()
    card = json.loads(json.dumps(SCORECARD))
    for mid in ("owner_fcf_yield", "margin_of_safety"):
        anchor = scorecard.ANCHORS[mid]
        card["metrics"][mid] = {"value": None, "points": None, "max": anchor["points"],
                                "pct": None,
                                "detail": f"{anchor['label']}: not computable — no market "
                                          f"cap (§4.2)"}
        card["coverage"]["missing"].append(
            {"metric": mid, "label": anchor["label"], "block": "price",
             "points": anchor["points"], "reason": "no market cap"})
    card["blocks"]["price"] = {"points": 0.0, "max": 0, "metrics": []}
    card["score"] = round(sum(b["points"] for b in card["blocks"].values()), 1)
    card["available_max"] = card["coverage"]["available_max"] = sum(
        b["max"] for b in card["blocks"].values())
    card["pct"] = round(100.0 * card["score"] / card["available_max"])
    card["band"] = scorecard.NO_PRICE_BAND
    card["band_meaning"] = scorecard.NO_PRICE_MEANING
    card["consensus"]["lenses"]["scorecard"] = None
    grades["names"][0]["scorecard"] = card
    path = tmp_path / "noprice-grades.json"
    path.write_text(json.dumps(grades), encoding="utf-8")
    doc = datasheet.build(path, cache_dir=workdir["cache"], top=10,
                          out=tmp_path / "noprice.html").read_text(encoding="utf-8")

    assert "NO PRICE" in doc                                   # the literal band
    assert "NOT a verdict" in doc and "Quality profile only" in doc
    assert "<span class='sc-max'>/100</span>" not in doc       # no 0-100 headline at all
    assert f"{card['score']:g}/{card['available_max']} pt" in doc
    assert f"<b>NO PRICE</b> · {card['score']:g}/{card['available_max']} pt" in doc
    assert "sc-band noverdict" in doc                          # flagged, not badged green
    assert "Prijs" in doc and "0/0" in doc                     # the empty Price block


def test_card_without_a_scorecard_degrades_but_still_builds(workdir, tmp_path):
    grades = _grades()
    grades["names"][0].pop("scorecard")
    path = tmp_path / "nocard-grades.json"
    path.write_text(json.dumps(grades), encoding="utf-8")
    doc = datasheet.build(path, cache_dir=workdir["cache"], top=10,
                          out=tmp_path / "nocard.html").read_text(encoding="utf-8")
    assert "Geen scorecard in deze grades-JSON" in doc
    assert "Score-opbouw per leg" in doc                        # everything else survives
    assert "recomputeComposite" in doc
    island = json.loads(re.search(
        r'<script type="application/json" id="scout-data">(.*?)</script>', doc, re.S)
        .group(1))
    assert island["cards"][0]["scorecard"] is None              # the JS then skips it


def test_the_whole_pre_existing_evidence_chain_still_renders(built_html):
    """The scorecard is added ABOVE the old card, never in place of it (§5.7)."""
    for anchor in ("Score-opbouw per leg", "Sectorpercentiel", "Legscore",
                   "Pijlers × gewichten → composite", "0.40·Q + 0.25·G + 0.20·D + 0.15·M",
                   "Veto/straf-checks (werkelijke waarden)", "Leverage-veto",
                   "Dilutiestraf", "Flags", "Eigen EV vs Yahoo-EV",
                   "Owner-FCF per periode", "Onderhouds-proxy",
                   "Jaarrekening-regels (gematchte labels)", "fast_info-snapshot",
                   "Veiligheidsmarge", "Buffett-checklist", "Alles uitklappen",
                   "prefers-color-scheme", "recomputeComposite", "De Formatie 2026Q3"):
        assert anchor in built_html, anchor


# --------------------------------------------- percent vs fraction units (§3.3)

def test_pct_never_guesses_units_from_magnitude():
    # ev.gap_pct is stored in PERCENT, mos.mos_pct as a FRACTION — the two overlap
    # exactly where a magnitude guess breaks (|x| around 1.5).
    assert datasheet._pct(1.2, stored="percent") == "1.2%"          # not 120.0%
    assert datasheet._pct(1.5, stored="percent") == "1.5%"          # the old boundary
    assert datasheet._pct(-0.8, stored="percent") == "-0.8%"
    assert datasheet._pct(23.5, stored="percent") == "23.5%"
    assert datasheet._pct(1.8, stored="fraction", signed=True) == "+180.0%"   # not +1.8%
    assert datasheet._pct(0.214, stored="fraction", signed=True) == "+21.4%"
    assert datasheet._pct(None, stored="fraction") == "—"
    with pytest.raises(ValueError):
        datasheet._pct(0.5, stored="maybe")                          # no guessing allowed


def test_html_renders_small_ev_gap_and_large_mos_correctly(workdir, tmp_path):
    grades = _grades()
    row = grades["names"][0]
    row["ev"] = {"own": 8.9e9, "yahoo": 8.79e9, "gap_pct": 1.2}      # percent: 1.2%
    row["mos"]["mos_pct"] = 1.8                                      # fraction: +180%
    path = tmp_path / "boundary-grades.json"
    path.write_text(json.dumps(grades), encoding="utf-8")
    doc = datasheet.build(path, cache_dir=workdir["cache"], top=10,
                          out=tmp_path / "boundary.html").read_text(encoding="utf-8")
    assert "gat: <span>1.2%</span>" in doc                            # not 120.0%
    assert "120.0%" not in doc
    assert ">+180.0%<" in doc                                         # not +1.8%
    assert "+1.8%" not in doc


def test_ev_row_surfaces_yahoo_source_when_present_and_degrades_when_not(workdir, tmp_path):
    def build_with(ev: dict, name: str) -> str:
        grades = _grades()
        grades["names"][0]["ev"] = ev
        path = tmp_path / f"{name}-grades.json"
        path.write_text(json.dumps(grades), encoding="utf-8")
        return datasheet.build(path, cache_dir=None, top=10,
                               out=tmp_path / f"{name}.html").read_text(encoding="utf-8")

    derived = build_with({"own": 8.9e9, "yahoo": 8.4e9, "gap_pct": 5.6,
                          "yahoo_source": "derived"}, "derived")
    assert "Referentie-EV (afgeleid" in derived
    field = build_with({"own": 8.9e9, "yahoo": 10.6e9, "gap_pct": 19.1,
                        "yahoo_source": "field"}, "field")
    assert "Yahoo-EV (fast_info)" in field
    legacy = build_with({"own": 8.9e9, "yahoo": 10.6e9, "gap_pct": 19.1}, "legacy")
    assert "Yahoo-EV:" in legacy                     # no key -> neutral label, no crash


# ------------------------------------------------- v3 weights come from the constant

def test_quality_formula_is_rendered_from_w_quality(built_html, workdir, tmp_path,
                                                    monkeypatch):
    assert datasheet.W_QUALITY == {"q": 0.40, "g": 0.25, "d": 0.20, "m": 0.15}
    formula = datasheet._weight_formula(datasheet.W_QUALITY)
    assert formula == "0.40·Q + 0.25·G + 0.20·D + 0.15·M"
    assert formula in built_html                     # the page shows the real constant
    # ...and it is genuinely derived: change the constant, the page follows.
    monkeypatch.setattr(datasheet, "W_QUALITY",
                        {"q": 0.50, "g": 0.20, "d": 0.20, "m": 0.10})
    doc = datasheet.build(workdir["grades"], cache_dir=None, top=10,
                          out=tmp_path / "reweighted.html").read_text(encoding="utf-8")
    assert "0.50·Q + 0.20·G + 0.20·D + 0.10·M" in doc
    assert formula not in doc


def test_build_degrades_gracefully_without_cache(workdir):
    out = datasheet.build(workdir["grades"], cache_dir=None,
                          stage2_dir=workdir["data"], top=10,
                          out=workdir["tmp"] / "no-cache.html")
    doc = out.read_text(encoding="utf-8")
    assert "v_yield" in doc                        # score build-up still complete
    assert "Geen cache-gegevens" in doc            # per-name evidence degrades, build survives
    assert "recomputeComposite" in doc


# ===================== the inversion layer in the audit (docs/INVERSION-DESIGN.md) =======
#
# datasheet.py renders what the layer produced; it computes no verdict and judges none.
# The fixtures below are the §5 shape grade.py stores on the row, written out here so the
# page is pinned against the contract rather than against another module's behaviour.

def _inversion(verdict="Fragile"):
    """The §5 shape as inversion.py actually emits it: probe ids from inversion.PROBES,
    a `measured` bit beside every severity (an unmeasured probe reports severity "none" —
    the coverage bit is the only thing that says it found nothing), and the coverage keys
    the layer really writes. A fixture that invents its own spelling validates the page
    against a contract no producer implements."""
    return {
        "verdict": verdict,
        "failure_modes": ["de kasmotor viel 89% terug vanaf zijn piek in 2010",
                          "de koers stond 52% onder zijn top"],
        "probes": {
            "price_drawdown": {"id": "price_drawdown", "severity": "severe",
                               "measured": True, "value": -0.523,
                               "sentence": "diepste piek-tot-dal −52.3%, niet hersteld",
                               "evidence": {}},
            "cash_engine": {"id": "cash_engine", "severity": "severe", "measured": True,
                            "value": -0.89, "evidence": {}},
            "predictability": {"id": "predictability", "severity": "caution",
                               "measured": True, "value": 0.42, "evidence": {}},
            "stress": {"id": "stress", "severity": "none", "measured": True, "value": 0.0,
                       "evidence": {}},
            "concentration": {"id": "concentration", "severity": "none", "measured": False,
                              "value": None, "evidence": {}},
        },
        "coverage": {"measured_counting": 6, "counting_total": 7, "thin": False,
                     "required_missing": [],
                     "unmeasured": [{"id": "concentration",
                                     "label": "customer concentration", "section": "3.7",
                                     "counts": False,
                                     "reason": "deze filer tagt geen klantconcentratie"}]},
        "notes": ["ConcentrationRiskPercentage1 niet getagd door deze filer — stilte is "
                  "geen veiligheid"],
    }


def _judged_grades(verdict="Fragile", **overrides):
    """The §3.3 doc with an inversion result on the row AND on the card, the way grade.py
    writes it."""
    grades = _grades()
    result = _inversion(verdict) | overrides
    row = grades["names"][0]
    row["inversion"] = result
    row["scorecard"]["inversion"] = result
    row["scorecard"]["consensus"] = {
        "green": 3, "of": 4,
        "lenses": {"scorecard": True, "margin_of_safety": True, "buffett": True,
                   "survival": False},
        "label": "3 of 4",
        "evidence": {"scorecard": "scorecard 82% (>= 60%)",
                     "margin_of_safety": "margin of safety +21% (> 0%)",
                     "buffett": "Buffett 11/13 (>= 9)",
                     "survival": "inversion Fragile — de kasmotor viel 89% terug"}}
    return grades


@pytest.fixture()
def judged_html(workdir):
    def build(verdict="Fragile", **overrides):
        workdir["grades"].write_text(json.dumps(_judged_grades(verdict, **overrides)),
                                     encoding="utf-8")
        out = datasheet.build(workdir["grades"], cache_dir=workdir["cache"],
                              stage2_dir=workdir["data"], top=10,
                              out=workdir["tmp"] / "judged.html")
        return out.read_text(encoding="utf-8")
    return build


def test_the_audit_renders_the_verdict_and_its_failure_modes(judged_html):
    doc = judged_html("Fragile")
    assert "Inversie — hoe zou dit mijn geld verliezen?" in doc
    assert "iv-verdict sev'>Fragile<" in doc
    assert "Hoe dit je geld kost" in doc
    assert "de kasmotor viel 89% terug vanaf zijn piek in 2010" in doc
    assert "de koers stond 52% onder zijn top" in doc
    assert "verschuift geen enkel punt" in doc          # §2, said on the page itself
    assert "fragiliteit: Fragile" in doc                # the chip on the closed card


def test_every_probe_shows_its_value_and_its_severity(judged_html):
    doc = judged_html()
    assert "Ruïne al aangetoond — koersdrawdown (§3.1)" in doc
    assert "-0.523" in doc and "-0.89" in doc           # measured values, not rounded away
    assert "diepste piek-tot-dal −52.3%, niet hersteld" in doc
    assert doc.count("sev-severe'>ernstig<") == 2
    assert "sev-caution'>let op<" in doc
    assert "sev-none'>geen<" in doc
    assert "sev-unknown'>niet gemeten<" in doc          # never rendered as "geen"
    assert "De kasmotor breekt — owner-FCF-drawdown (§3.3)" in doc


def test_the_coverage_line_names_the_probes_that_were_not_measured(judged_html):
    doc = judged_html()
    assert "<b>6 van 7</b> tellende probes gemeten" in doc
    assert "niet gemeten, en daarom niet als veilig te lezen" in doc
    assert "Concentratie — alleen een vlag (§3.7)" in doc
    assert "stilte is geen veiligheid" in doc           # the layer's own note rides along


def test_coverage_that_counts_without_naming_says_so(judged_html):
    doc = judged_html(coverage={"scored": 4, "of": 7}, probes={})
    assert "welke probes ontbreken is niet vastgelegd" in doc
    assert "onbekend is niet hetzelfde als veilig" in doc


def test_an_unknown_verdict_is_said_out_loud_and_never_read_as_safe(judged_html):
    doc = judged_html("Unknown", failure_modes=[])
    assert "iv-verdict '>Unknown<" in doc               # neutral chip, not the calm one
    assert "Te weinig bewijs om te zeggen hoe dit breekt" in doc
    assert "niet als veilig gelezen" in doc


def test_exceptional_and_fragile_are_shown_together_never_reconciled(judged_html):
    """§5: the pairing is the point. The score keeps its headline, the verdict keeps its
    chip, and the consensus shows the fourth lens voting no."""
    doc = judged_html("Fragile")
    card = _judged_grades()["names"][0]["scorecard"]
    assert (card["pct"], card["band"]) == (91, "Exceptional")
    assert "sc-score'>91</span><span class='sc-max'>/100" in doc      # the score is intact
    assert "sc-band'>Exceptional<" in doc
    assert "iv-verdict sev'>Fragile<" in doc                          # ...and so is the verdict
    assert "Overleving (inversielaag)" in doc                         # the 4th lens, named
    assert "Consensus 3/4" in doc
    assert "inversion Fragile — de kasmotor viel 89% terug" in doc


def test_the_header_reports_the_fragility_occupancy(judged_html):
    doc = judged_html("Ruinous")
    assert "Fragiliteit (inversielaag, naast de score)" in doc
    assert "Ruinous × 1" in doc


def test_a_grades_json_without_verdicts_renders_the_page_it_always_did(built_html):
    """The ~470 price-less names, and every grades JSON written before this layer: no
    inversion block at all, and nothing else disturbed."""
    assert "Inversie — hoe zou dit mijn geld verliezen?" not in built_html
    assert "fragiliteit:" not in built_html
    assert "Fragiliteit (inversielaag" not in built_html


def test_the_whole_evidence_chain_survives_the_new_block(judged_html):
    """Nothing was traded away for the new section: both recompute checks, Stage-2, the
    ramps, the anchor ledger, MoS, Buffett, the statements, and self-containment."""
    doc = judged_html()
    for marker in ("recomputeComposite", "recomputeScorecard", "sc-recheck-TEST",
                   "recheck-TEST", "NIEUWSTE-LAAG-MARKER", "Punten per metriek",
                   "0 bij 5.00% · vol bij 25.00%", "De ankers en hun herkomst",
                   "Veiligheidsmarge (schaduw-DCF", "Buffett-checklist", "v_yield",
                   "Owner's Scorecard — absolute punten", "Alles uitklappen"):
        assert marker in doc, marker
    assert "http://" not in doc and "https://" not in doc      # no external asset
    assert "prefers-color-scheme: dark" in doc                 # both themes intact
    assert doc.count("<script") == 2                           # island + inline JS only


def test_the_probes_may_arrive_as_a_list_too(judged_html):
    """The probe container's shape is the other module's to choose; both are rendered."""
    doc = judged_html(probes=[{"probe": "price_drawdown", "severity": "severe",
                               "value": -0.716},
                              {"id": "return_asymmetry", "severity": "caution",
                               "value": -0.47}])
    assert "-0.716" in doc and "-0.47" in doc
    assert "Ruïne al aangetoond — koersdrawdown (§3.1)" in doc
    assert "Rendementsasymmetrie — scheefheid &amp; staartverhouding (§3.2)" in doc


def test_a_probe_id_the_label_table_does_not_know_is_shown_not_dropped(judged_html):
    doc = judged_html(probes={"brand_new_probe": {"severity": "severe", "value": 1.5}})
    assert "brand_new_probe" in doc and "1.5" in doc


def test_a_real_inversion_result_never_paints_an_unmeasured_probe_green(judged_html):
    """Built by the LAYER, not by this file. inversion.py deliberately returns severity
    "none" with measured=False for a probe that found no evidence, so a page that reads the
    severity alone shows every gap as a clean green "geen" — the §7 inversion, on the one
    surface whose whole job is auditing the verdict."""
    import inversion

    bundle = {
        "symbol": "TEST", "name": "Test Corp", "sector": "Information Technology",
        "industry": "Software", "market_cap": 6.0e9, "price": 60.0,
        "shares_series": [["2016-01-01", 100e6]], "splits": {},
        "annual": {"income": {}, "balance": {}, "cashflow": {}}, "quarterly": {},
    }
    result = inversion.inversion(bundle)               # every probe unmeasured
    assert result["verdict"] == "Unknown"
    assert all(p["severity"] == "none" for p in result["probes"].values())
    assert all(p["measured"] is False for p in result["probes"].values())

    doc = judged_html("Unknown", **{k: result[k] for k in
                                    ("failure_modes", "probes", "coverage", "notes")})
    assert "sev-none'>geen<" not in doc                # not one gap rendered as clean
    assert doc.count("sev-unknown'>niet gemeten<") == len(inversion.PROBES)
    assert "<b>0 van 6</b> tellende probes gemeten" in doc
    assert "De kasmotor breekt — owner-FCF-drawdown (§3.3)" in doc   # §3.3 is labelled
    assert "cash_engine</span></td>" in doc                          # ...and keyed right
    # the two probes §4 cannot certify without, named as the reason for Unknown
    assert "het verdict valt terug op Unknown (§4)" in doc
    assert "Ruïne al aangetoond — koersdrawdown (§3.1), De kasmotor breekt" in doc


def test_a_verdict_without_probes_still_renders_the_verdict(judged_html):
    doc = judged_html(probes={}, coverage={})
    assert "iv-verdict sev'>Fragile<" in doc
    assert "leverde geen probes bij dit verdict" in doc
    assert "dekking niet vastgelegd door de laag" in doc
