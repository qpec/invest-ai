"""Offline tests for datasheet.py (spec §5.7, §3.3, §3.5): synthetic grades JSON
(one graded name with flags+MoS+Buffett, one vetoed) + cache entry + Stage-2 files;
assert the HTML carries the evidence chain, the JSON island + JS recompute, no
external asset references, and that the Stage-2 date-fallback picks the newest
file ≤ run date. No network, no real caches."""
from __future__ import annotations

import json
import re

import pytest

import datasheet

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
                  "detail": "NI daalde in 2024"}]}},
            {"symbol": "BADCO", "name": "Bad Leverage Co.",
             "sector": "Health Care", "industry": "Health Care Technology", "tier": "Core",
             "grade": "VETOED", "composite": None, "quality_score": None,
             "pillars": {"v": None, "q": None, "g": None, "d": None, "m": None},
             "legs": {},
             "veto": {"vetoed": True, "penalty": 0,
                      "reason": "leverage veto: net debt/EBITDA above the §2 floor"},
             "flags": [], "ev": None,
             "ttm": {"quarters": 0, "through": None, "basis": "annual"},
             "mos": None, "buffett": None},
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
