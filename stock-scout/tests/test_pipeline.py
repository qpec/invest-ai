"""End-to-end offline pipeline test: cache + universe -> grade.py -> datasheet.py.

One synthetic §3.2 cache dir + universe.csv (8 names, 2 sectors) exercising a
leverage veto, a dilution veto, a SHARE_CLASS-flagged name, a clean A/B grade
(ADBE — overlapping the checked-in data/stage2-2026-07-30.json) and an
INSUFFICIENT name. grade.main runs with the pinned --date 2026-07-30 so the
Stage-2 file engages; datasheet.main then renders the produced grades JSON.
Asserts the §3.3 schema and count identity (graded+vetoed+insufficient ==
universe), the §5.5 report sections, formation-state.json idempotence on a
same-date re-run, Stage-2 verdict embedding + the recompute JS (§5.7), and the
msg-62 quarter discipline: streaks advance exactly once per real quarter change.
No network — a module-wide socket guard proves it.
"""
from __future__ import annotations

import csv
import json
import os
import socket
from pathlib import Path

import pytest

import datasheet
import grade

RUN1 = "2026-07-30"          # pinned: matches the checked-in stage2 file (§3.5)
RUN_Q4 = "2026-10-30"        # next calendar quarter (2026Q4)
RUN_Q1 = "2027-01-30"        # the quarter after that (2027Q1)
REPO_DATA = Path(__file__).resolve().parent.parent / "data"

YEARS = ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
QTRS = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]

LEG_IDS = {"v_yield", "q_roic", "q_gm", "q_ofcf_margin", "g_revenue", "g_ps_ofcf",
           "d_net_debt", "d_self_funding", "d_sbc", "m_shares", "m_accruals"}
LEG_KEYS = {"raw", "percentile", "cohort_n", "score", "note"}
TOP_KEYS = {"run_date", "version", "universe", "graded", "vetoed", "insufficient",
            "names", "portfolio", "formation"}
NAME_KEYS = {"symbol", "name", "sector", "industry", "tier", "grade", "composite",
             "quality_score", "pillars", "legs", "veto", "flags", "ev", "ttm",
             "mos", "buffett"}
GRADE_LETTERS = ("A", "B", "C", "D", "F")

FLAT_SHARES = {f"{y}-06-30": 100e6 for y in range(2021, 2026)}


def cache_entry(symbol, *, sector, industry, name, q_ocf=70e6, q_sbc=5e6,
                total_debt=100e6, cash=300e6, enterprise_value=None,
                minority_interest=0.0, gm=0.60, gm_wobble=0.02,
                rev_step=0.1e9, shares=None, no_balance=False):
    """A §3.2 cache entry on the quarterly TTM basis. Knobs make one name a
    leverage-veto (total_debt), a dilution-veto (shares), a SHARE_CLASS case
    (minority_interest + enterprise_value), the cohort winner (q_ocf, gm,
    rev_step, buyback shares) or INSUFFICIENT (no_balance -> no EV -> no yield)."""
    bal = {"Total Debt": total_debt, "Cash And Cash Equivalents": cash,
           "Working Capital": 200e6, "Total Assets": 2e9, "Current Assets": 800e6,
           "Current Liabilities": 400e6, "Stockholders Equity": 1e9,
           "Minority Interest": minority_interest}
    ann_inc, ann_bal, ann_cf, q_inc, q_cf = {}, {}, {}, {}, {}
    for i, pe in enumerate(YEARS):
        rev = 1.0e9 + i * rev_step
        margin = gm + gm_wobble * (1 if i % 2 else -1)
        ann_inc[pe] = {"Total Revenue": rev, "EBIT": 250e6, "EBITDA": 320e6,
                       "Gross Profit": margin * rev, "Operating Income": 0.25 * rev,
                       "Net Income": 170e6 + i * 10e6,
                       "Net Income Including Noncontrolling Interests": 170e6 + i * 10e6,
                       "Interest Expense": 5e6}
        ann_bal[pe] = dict(bal)
        ann_cf[pe] = {"Operating Cash Flow": 280e6, "Capital Expenditure": -50e6,
                      "Stock Based Compensation": 20e6,
                      "Depreciation And Amortization": 60e6}
    for pe in QTRS:
        q_inc[pe] = {"Total Revenue": 320e6, "EBIT": 65e6, "EBITDA": 80e6,
                     "Gross Profit": gm * 320e6, "Operating Income": 80e6,
                     "Net Income": 55e6,
                     "Net Income Including Noncontrolling Interests": 55e6,
                     "Interest Expense": 1.25e6}
        q_cf[pe] = {"Operating Cash Flow": q_ocf, "Capital Expenditure": -12e6,
                    "Stock Based Compensation": q_sbc,
                    "Depreciation And Amortization": 15e6}
    fast_info = {"last_price": 100.0, "market_cap": 10e9, "shares": 100e6,
                 "currency": "USD"}
    if enterprise_value is not None:
        fast_info["enterprise_value"] = enterprise_value
    return {
        "ticker": symbol, "fetched_at": "2026-07-30T05:00:00+00:00",
        "meta": {"name": name, "sector": sector, "industry": industry,
                 "country": "United States"},
        "currency": "USD", "price": {"close": 100.0, "date": "2026-07-29"},
        "fast_info": fast_info,
        "shares": dict(shares if shares is not None else FLAT_SHARES),
        "annual": {"income": ann_inc, "balance": {} if no_balance else ann_bal,
                   "cashflow": ann_cf},
        "quarterly": {"income": q_inc,
                      "balance": {} if no_balance else {QTRS[-1]: dict(bal)},
                      "cashflow": q_cf},
    }


IT, HC = "Information Technology", "Health Care"
ENTRIES = {
    # Cohort winner on every leg -> A/B grade; overlaps the checked-in Stage-2 file.
    "ADBE": dict(sector=IT, industry="Software", name="Adobe Inc.", q_ocf=100e6,
                 q_sbc=3e6, total_debt=50e6, cash=500e6, gm=0.65, gm_wobble=0.0,
                 rev_step=0.17e9,
                 shares={f"{2021 + i}-06-30": (108 - 2 * i) * 1e6 for i in range(5)}),
    "BBB": dict(sector=IT, industry="Software", name="Beta Platforms Inc."),
    # NCI 23% of total equity AND own-EV gap 23.5% -> SHARE_CLASS (+EV_GAP), graded.
    "SHCX": dict(sector=IT, industry="Software", name="ShareClass Holdings",
                 minority_interest=300e6, enterprise_value=7.5e9),
    # Lowest owner-FCF yield of the 4 graded IT names -> V-pctl 12.5 -> fails the gate.
    "GATEX": dict(sector=IT, industry="IT Services", name="Gate Fail Corp.", q_ocf=60e6),
    # Net debt/EBITDA (5e9-100e6)/320e6 = 15.3 > 4 -> leverage veto.
    "LEVX": dict(sector=IT, industry="Software", name="Overlevered Corp.",
                 total_debt=5e9, cash=100e6),
    # Shares +150%/yr -> hard dilution veto (>20%/yr).
    "DILX": dict(sector=IT, industry="Software", name="Diluter Inc.",
                 shares={"2023-06-30": 80e6, "2024-06-30": 100e6, "2025-06-30": 250e6}),
    "CCC": dict(sector=HC, industry="Biotechnology", name="Gamma Biotech Inc."),
    # No balance data -> no own EV -> owner-FCF yield None -> INSUFFICIENT.
    "INSX": dict(sector=HC, industry="Biotechnology", name="No Balance Corp.",
                 no_balance=True),
}


@pytest.fixture(scope="module")
def _no_network():
    """Fail loudly if anything in the pipeline connects a socket (task item 4)."""
    real_connect, real_create = socket.socket.connect, socket.create_connection

    def guard(*args, **kwargs):
        raise AssertionError("network access attempted during the offline pipeline test")

    socket.socket.connect = guard
    socket.create_connection = guard
    try:
        yield
    finally:
        socket.socket.connect = real_connect
        socket.create_connection = real_create


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory, _no_network):
    """Run the whole pipeline once and snapshot every stage the tests assert on."""
    root = tmp_path_factory.mktemp("pipeline")
    (root / "cache").mkdir()
    for symbol, kw in ENTRIES.items():
        (root / "cache" / f"{symbol}.json").write_text(
            json.dumps(cache_entry(symbol, **kw), allow_nan=False), encoding="utf-8")
    with open(root / "universe.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "name", "sector", "industry", "country", "market_cap",
                    "exchange", "currency"])
        for symbol, kw in ENTRIES.items():
            w.writerow([symbol, kw["name"], kw["sector"], kw["industry"],
                        "United States", "Large Cap", "NMS", "USD"])

    old_cwd = os.getcwd()
    os.chdir(root)
    try:
        p = {"root": root}
        state_path = root / "formation-state.json"

        assert grade.main(["--date", RUN1]) == 0
        p["doc1"] = json.loads((root / "reports" / f"scout-grades-{RUN1}.json")
                               .read_text(encoding="utf-8"))
        p["md1"] = (root / "reports" / f"scout-run-{RUN1}.md").read_text(encoding="utf-8")
        p["state1_text"] = state_path.read_text(encoding="utf-8")
        p["state1"] = json.loads(p["state1_text"])

        assert grade.main(["--date", RUN1]) == 0          # same-date re-run (msg 62)
        p["state1_rerun_text"] = state_path.read_text(encoding="utf-8")

        grades_path = root / "reports" / f"scout-grades-{RUN1}.json"
        assert datasheet.main(["--grades", str(grades_path),
                               "--stage2-dir", str(REPO_DATA)]) == 0
        p["datasheet_html"] = (root / "reports" / f"datasheet-{RUN1}.html"
                               ).read_text(encoding="utf-8")

        # GATEX's yield improves -> it passes the V gate from the Q4 run onward.
        bumped = cache_entry("GATEX", **{**ENTRIES["GATEX"], "q_ocf": 90e6})
        (root / "cache" / "GATEX.json").write_text(
            json.dumps(bumped, allow_nan=False), encoding="utf-8")

        assert grade.main(["--date", RUN_Q4]) == 0        # quarter rollover
        p["state_q4"] = json.loads(state_path.read_text(encoding="utf-8"))
        assert grade.main(["--date", RUN_Q4]) == 0        # same-quarter re-run
        p["state_q4_rerun"] = json.loads(state_path.read_text(encoding="utf-8"))
        assert grade.main(["--date", RUN_Q1]) == 0        # next quarter -> promotion
        p["state_q1"] = json.loads(state_path.read_text(encoding="utf-8"))
        return p
    finally:
        os.chdir(old_cwd)


# ------------------------------------------------------------- grades JSON (§3.3)

def test_grades_json_schema_and_count_identity(pipeline):
    doc = pipeline["doc1"]
    assert TOP_KEYS <= set(doc)
    assert doc["run_date"] == RUN1
    assert doc["version"] == "v2.3+v3"
    assert doc["universe"] == len(ENTRIES) == len(doc["names"])
    assert doc["graded"] + doc["vetoed"] + doc["insufficient"] == doc["universe"]
    assert (doc["graded"], doc["vetoed"], doc["insufficient"]) == (5, 2, 1)
    for row in doc["names"]:
        assert NAME_KEYS <= set(row)
        assert set(row["pillars"]) == set("vqgdm")
        assert set(row["veto"]) == {"vetoed", "reason", "penalty"}
        assert set(row["ev"]) == {"own", "yahoo", "gap_pct", "yahoo_source"}
        assert set(row["ttm"]) == {"quarters", "through", "basis"}
        if row["grade"] in GRADE_LETTERS:
            assert set(row["legs"]) == LEG_IDS
            for leg in row["legs"].values():
                assert LEG_KEYS <= set(leg)


def test_personas_veto_flag_grade_insufficient(pipeline):
    rows = {r["symbol"]: r for r in pipeline["doc1"]["names"]}
    levx = rows["LEVX"]
    assert levx["grade"] == "VETOED" and "leverage veto" in levx["veto"]["reason"]
    dilx = rows["DILX"]
    assert dilx["grade"] == "VETOED" and "dilution veto" in dilx["veto"]["reason"]
    shcx = rows["SHCX"]
    assert shcx["grade"] in GRADE_LETTERS
    assert {"SHARE_CLASS", "EV_GAP"} <= {f["code"] for f in shcx["flags"]}
    assert shcx["legs"]["m_shares"]["score"] == 50.0      # leg neutral under SHARE_CLASS
    assert shcx["veto"]["penalty"] == 0                   # dilution penalty suppressed
    insx = rows["INSX"]
    assert insx["grade"] == "INSUFFICIENT"
    assert insx["composite"] is None and insx["mos"] is None
    adbe = rows["ADBE"]
    assert adbe["grade"] in ("A", "B")                    # the clean cohort winner
    assert adbe["mos"] is not None and adbe["buffett"]["max"] == 13
    assert rows["GATEX"]["grade"] in GRADE_LETTERS
    assert rows["GATEX"]["pillars"]["v"] < 20.0           # fails the entry gate on run 1


# --------------------------------------------------------------- report md (§5.5)

def test_report_md_pinned_sections(pipeline):
    md = pipeline["md1"]
    assert md.startswith(f"# Stock Scout — run {RUN1} (v2.3+v3)")
    assert "Veto-verdeling:" in md
    assert "- leverage veto: 1" in md
    assert "- dilution veto: 1" in md
    assert "## Core" in md                                # Software tier table
    assert "## NL-namen" in md
    assert f"## De Formatie (2026Q3)" in md
    assert "liever cash dan een kandidaat zonder bewijs" in md
    assert "research-shortlist, geen kooplijst" in md     # honest-evidence footer


# ------------------------------------------------- formation idempotence (msg 62)

def test_formation_written_and_same_date_rerun_identical(pipeline):
    assert pipeline["doc1"]["formation"] == pipeline["state1"]
    assert pipeline["state1_rerun_text"] == pipeline["state1_text"]
    state = pipeline["state1"]
    assert state["quarter"] == "2026Q3" and state["slots"] == 15
    assert {m["symbol"] for m in state["squad"]} == {"ADBE", "BBB", "SHCX", "CCC"}
    assert state["bench"] == []                           # GATEX gate-blocked, no bench


# ------------------------------------------------------------- datasheet (§5.7)

def test_datasheet_embeds_stage2_and_recompute_js(pipeline):
    html_text = pipeline["datasheet_html"]
    assert f"stage2-{RUN1}.json" in html_text             # the checked-in file engaged
    assert "Stage-2-analyse" in html_text
    assert "Sterke kandidaat" in html_text                # ADBE's checked-in verdict
    assert 'id="scout-data"' in html_text                 # JSON island for the recompute
    assert "recomputeComposite" in html_text              # the independent JS recheck
    assert "recheck-ADBE" in html_text                    # per-card recompute target
    assert "Alles uitklappen" in html_text


# ------------------------------------------- quarter rollover streaks (msg 62)

def test_quarter_rollover_advances_streaks_exactly_once(pipeline):
    q4 = pipeline["state_q4"]
    assert q4["quarter"] == "2026Q4"
    # Squad: bootstrap streak 1 -> 2, exactly once; SHCX now fails the gate but
    # V-pctl >= 5 so it stays seated (no exit on gate failure).
    assert {m["symbol"] for m in q4["squad"]} == {"ADBE", "BBB", "SHCX", "CCC"}
    assert all(m["streak"] == 2 for m in q4["squad"])
    # GATEX (now through the gate) lands on the bench with streak 1 of 2.
    assert [dict(b) for b in q4["bench"]] == [{"symbol": "GATEX", "streak": 1,
                                               "needed": 2}]
    # Same-quarter re-run: no unearned advance anywhere.
    q4b = pipeline["state_q4_rerun"]
    assert all(m["streak"] == 2 for m in q4b["squad"])
    assert q4b["bench"][0]["streak"] == 1
    # Next real quarter: bench streak 1 -> 2 (exactly once) and GATEX is promoted.
    q1 = pipeline["state_q1"]
    assert q1["quarter"] == "2027Q1"
    gatex = next(m for m in q1["squad"] if m["symbol"] == "GATEX")
    assert gatex["streak"] == 2 and gatex["since"] == "2027Q1"
    assert all(m["streak"] == 3 for m in q1["squad"] if m["symbol"] != "GATEX")
    promos = [t for t in q1["transfers"]
              if t["symbol"] == "GATEX" and t["action"] == "in"]
    assert len(promos) == 1 and "twee kwartalen bewijs" in promos[0]["reason"]
    assert q1["bench"] == []
