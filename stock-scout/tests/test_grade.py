"""Offline tests for grade.py (spec §5.5, §3.3): a synthetic §3.2 cache dir (6 names,
2 sectors, one vetoed, one flagged, one uncached) -> grade.main with --date pinned ->
grades JSON schema, report md sections (De Formatie, veto breakdown, NL call-out),
formation-state.json creation and same-date idempotence. No network, no real caches."""
from __future__ import annotations

import argparse
import csv
import json

import pytest

import formation
import grade
import scoring

RUN_DATE = "2026-07-30"
YEARS = ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
QTRS = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]

BAL_CELL = {
    "Total Debt": 100e6, "Cash And Cash Equivalents": 300e6, "Working Capital": 200e6,
    "Total Assets": 2e9, "Current Assets": 800e6, "Current Liabilities": 400e6,
    "Stockholders Equity": 1e9, "Minority Interest": 0.0,
}

LEG_IDS = ("v_yield", "q_roic", "q_gm", "q_ofcf_margin", "g_revenue", "g_ps_ofcf",
           "d_net_debt", "d_self_funding", "d_sbc", "m_shares", "m_accruals")
NAME_KEYS = {"symbol", "name", "sector", "industry", "tier", "grade", "composite",
             "quality_score", "pillars", "legs", "veto", "flags", "ev", "ttm",
             "mos", "buffett"}


def cache_entry(symbol, sector, industry, name, *, q_ocf=70e6, total_debt=100e6,
                cash=300e6, enterprise_value=None):
    """A healthy, gradeable §3.2 cache entry (quarterly TTM basis); total_debt 5e9
    turns it into a leverage-veto name, enterprise_value far from own EV flags EV_GAP."""
    bal = dict(BAL_CELL, **{"Total Debt": total_debt, "Cash And Cash Equivalents": cash})
    ann_inc, ann_bal, ann_cf, q_inc, q_cf = {}, {}, {}, {}, {}
    for i, pe in enumerate(YEARS):
        rev = 1.0e9 + i * 0.1e9
        ann_inc[pe] = {"Total Revenue": rev, "EBIT": 250e6, "EBITDA": 320e6,
                       "Gross Profit": 0.6 * rev, "Operating Income": 0.25 * rev,
                       "Net Income": 170e6 + i * 10e6,
                       "Net Income Including Noncontrolling Interests": 170e6 + i * 10e6,
                       "Interest Expense": 5e6}
        ann_bal[pe] = dict(bal)
        ann_cf[pe] = {"Operating Cash Flow": 280e6, "Capital Expenditure": -50e6,
                      "Stock Based Compensation": 20e6,
                      "Depreciation And Amortization": 60e6}
    for pe in QTRS:
        q_inc[pe] = {"Total Revenue": 320e6, "EBIT": 65e6, "EBITDA": 80e6,
                     "Gross Profit": 192e6, "Operating Income": 80e6, "Net Income": 55e6,
                     "Net Income Including Noncontrolling Interests": 55e6,
                     "Interest Expense": 1.25e6}
        q_cf[pe] = {"Operating Cash Flow": q_ocf, "Capital Expenditure": -12e6,
                    "Stock Based Compensation": 5e6,
                    "Depreciation And Amortization": 15e6}
    fast_info = {"last_price": 100.0, "market_cap": 10e9, "shares": 100e6,
                 "currency": "USD"}
    if enterprise_value is not None:
        fast_info["enterprise_value"] = enterprise_value
    return {
        "ticker": symbol, "fetched_at": "2026-07-30T05:00:00+00:00",
        "meta": {"name": name, "sector": sector, "industry": industry,
                 "country": "Netherlands" if symbol.endswith(".AS") else "United States"},
        "currency": "USD", "price": {"close": 100.0, "date": "2026-07-29"},
        "fast_info": fast_info,
        "shares": {f"{y}-06-30": 100e6 for y in range(2021, 2026)},
        "annual": {"income": ann_inc, "balance": ann_bal, "cashflow": ann_cf},
        "quarterly": {"income": q_inc, "balance": {QTRS[-1]: dict(bal)},
                      "cashflow": q_cf},
    }


ENTRIES = {
    # IT cohort: FLGX has the lowest owner-FCF yield -> V-pctl 16.7 -> fails the gate.
    "AAA": dict(sector="Information Technology", industry="Software",
                name="Alpha Software Inc.", q_ocf=70e6),
    "BBB": dict(sector="Information Technology", industry="Software",
                name="Beta Platforms Inc.", q_ocf=80e6),
    "FLGX": dict(sector="Information Technology", industry="IT Services",
                 name="Flagged IT Services Corp.", q_ocf=60e6,
                 enterprise_value=7.5e9),                  # own EV 9.8e9 -> gap 23% -> EV_GAP
    "CCC": dict(sector="Health Care", industry="Biotechnology",
                name="Gamma Biotech Inc.", q_ocf=70e6),
    "PHIA.AS": dict(sector="Health Care", industry="Health Care Technology",
                    name="Koninklijke Philips N.V.", q_ocf=60e6),
    "VETX": dict(sector="Information Technology", industry="Software",
                 name="Overlevered Corp.", total_debt=5e9, cash=100e6),   # leverage veto
}


@pytest.fixture()
def rundir(tmp_path, monkeypatch):
    """A chdir'd working directory with universe.csv + cache/ (MISS stays uncached)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cache").mkdir()
    for symbol, kw in ENTRIES.items():
        entry = cache_entry(symbol, **kw)
        (tmp_path / "cache" / f"{symbol}.json").write_text(
            json.dumps(entry, allow_nan=False), encoding="utf-8")
    with open(tmp_path / "universe.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "name", "sector", "industry", "country", "market_cap",
                    "exchange", "currency"])
        for symbol, kw in ENTRIES.items():
            w.writerow([symbol, kw["name"], kw["sector"], kw["industry"],
                        "Netherlands" if symbol.endswith(".AS") else "United States",
                        "Large Cap", "AMS" if symbol.endswith(".AS") else "NMS",
                        "EUR" if symbol.endswith(".AS") else "USD"])
        w.writerow(["MISS", "Uncached Corp.", "Information Technology", "Software",
                    "United States", "Mid Cap", "NMS", "USD"])
    return tmp_path


@pytest.fixture()
def first_run(rundir):
    assert grade.main(["--date", RUN_DATE]) == 0
    doc = json.loads((rundir / "reports" / f"scout-grades-{RUN_DATE}.json")
                     .read_text(encoding="utf-8"))
    md = (rundir / "reports" / f"scout-run-{RUN_DATE}.md").read_text(encoding="utf-8")
    return rundir, doc, md


# --------------------------------------------------------------- bundle mapping

def test_build_bundle_maps_cache_to_bundle():
    entry = cache_entry("AAA", **ENTRIES["FLGX"] | {"name": "X"})
    b = grade.build_bundle(entry)
    assert b["symbol"] == "AAA"
    assert b["sector"] == "Information Technology"
    assert b["market_cap"] == 10e9                        # own market_cap from fast_info
    assert b["yahoo_ev"] == 7.5e9                         # yahoo_ev when present
    assert b["price"] == 100.0
    assert b["shares_series"][0] == ["2021-06-30", 100e6]  # ascending series
    assert b["shares_series"][-1][0] == "2025-06-30"
    assert b["annual"] is entry["annual"]                 # statements straight through
    assert b["quarterly"] is entry["quarterly"]


def test_build_bundle_accepts_camelcase_and_absent_ev():
    entry = cache_entry("AAA", **ENTRIES["AAA"])
    entry["fast_info"] = {"marketCap": 5e9, "lastPrice": 50.0}
    b = grade.build_bundle(entry)
    assert b["market_cap"] == 5e9
    assert b["yahoo_ev"] is None                          # EV_GAP can then never fire


# ------------------------------------------------------------ grades JSON (§3.3)

def test_grades_json_schema_and_counts(first_run):
    _, doc, _ = first_run
    assert set(doc) >= {"run_date", "version", "universe", "graded", "vetoed",
                        "insufficient", "names", "portfolio", "formation"}
    assert doc["run_date"] == RUN_DATE
    assert doc["version"] == "v2.3+v3"
    assert doc["universe"] == 7                           # incl. the uncached MISS
    assert doc["graded"] == 5
    assert doc["vetoed"] == 1
    assert doc["insufficient"] == 0
    assert len(doc["names"]) == 6                         # MISS skipped, never fabricated
    for row in doc["names"]:
        assert NAME_KEYS <= set(row)


def test_graded_name_carries_legs_mos_buffett(first_run):
    _, doc, _ = first_run
    rows = {r["symbol"]: r for r in doc["names"]}
    aaa = rows["AAA"]
    assert aaa["grade"] in "ABCDF"
    assert set(aaa["legs"]) == set(LEG_IDS)
    assert set(aaa["mos"]) == {"intrinsic_value", "market_cap", "mos_pct", "wacc",
                               "growth", "base_fcf"}
    assert aaa["mos"]["market_cap"] == 10e9
    assert aaa["buffett"]["max"] == 13
    assert aaa["ev"]["own"] == pytest.approx(9.8e9)
    assert aaa["ttm"] == {"quarters": 4, "through": QTRS[-1], "basis": "quarterly"}


def test_vetoed_name_suppressed_with_null_shadow_layers(first_run):
    _, doc, _ = first_run
    vetx = next(r for r in doc["names"] if r["symbol"] == "VETX")
    assert vetx["grade"] == "VETOED"
    assert "leverage" in vetx["veto"]["reason"]
    assert vetx["composite"] is None and vetx["quality_score"] is None
    assert vetx["mos"] is None and vetx["buffett"] is None


def test_flagged_name_has_ev_gap(first_run):
    _, doc, _ = first_run
    flgx = next(r for r in doc["names"] if r["symbol"] == "FLGX")
    assert "EV_GAP" in {f["code"] for f in flgx["flags"]}
    assert flgx["ev"]["yahoo"] == 7.5e9
    assert flgx["ev"]["gap_pct"] == pytest.approx(23.5, abs=0.1)


def test_portfolio_positions_clamped(first_run):
    _, doc, _ = first_run
    port = doc["portfolio"]
    assert {p["symbol"] for p in port["positions"]} == {"AAA", "BBB", "FLGX", "CCC",
                                                        "PHIA.AS"}
    assert all(p["weight"] <= scoring.MAX_POSITION_PCT + 1e-9 for p in port["positions"])
    assert port["cash"] == pytest.approx(1.0 - sum(p["weight"]
                                                   for p in port["positions"]))


# --------------------------------------------------------------- formation (§5.6)

def test_formation_state_written_and_embedded(first_run):
    rundir, doc, _ = first_run
    state = json.loads((rundir / "formation-state.json").read_text(encoding="utf-8"))
    assert doc["formation"] == state
    assert state["quarter"] == "2026Q3"
    assert state["slots"] == 15
    squad = {m["symbol"] for m in state["squad"]}
    assert squad == {"AAA", "BBB", "CCC", "PHIA.AS"}      # gate+rank passers, bootstrap
    assert "FLGX" not in squad                            # V-pctl 16.7 < 20: gate blocks
    assert all(t["action"] == "in" and "bootstrap" in t["reason"]
               for t in state["transfers"])


def test_second_same_date_run_idempotent_on_formation(first_run):
    rundir, _, _ = first_run
    state_path = rundir / "formation-state.json"
    before = json.loads(state_path.read_text(encoding="utf-8"))
    assert grade.main(["--date", RUN_DATE]) == 0          # same-quarter re-run (msg 62)
    after = json.loads(state_path.read_text(encoding="utf-8"))
    assert after == before                                # streaks + transfers untouched
    doc = json.loads((rundir / "reports" / f"scout-grades-{RUN_DATE}.json")
                     .read_text(encoding="utf-8"))
    assert doc["formation"] == before


def test_no_formation_flag_skips_update(rundir):
    assert grade.main(["--date", RUN_DATE, "--no-formation"]) == 0
    assert not (rundir / "formation-state.json").exists()
    doc = json.loads((rundir / "reports" / f"scout-grades-{RUN_DATE}.json")
                     .read_text(encoding="utf-8"))
    assert doc["formation"] is None
    md = (rundir / "reports" / f"scout-run-{RUN_DATE}.md").read_text(encoding="utf-8")
    assert "Formatie-update overgeslagen" in md


# ------------------------------------------------------------------ report md (§5.5)

def test_report_md_sections(first_run):
    _, _, md = first_run
    assert md.startswith(f"# Stock Scout — run {RUN_DATE} (v2.3+v3)")
    assert "niet in cache 1" in md
    assert "Veto-verdeling:" in md
    assert "- leverage veto: 1" in md
    assert "## Core" in md                                # Software tier section
    assert "## De Formatie (2026Q3)" in md
    assert "Open plekken: 11" in md                       # 4/15 bezet
    assert "liever cash dan een kandidaat zonder bewijs" in md
    assert "research-shortlist, geen kooplijst" in md     # honest-evidence footer


def test_report_md_nl_names_callout(first_run):
    _, _, md = first_run
    nl_section = md.split("## NL-namen", 1)[1]
    assert "PHIA.AS" in nl_section.split("##", 1)[0]


def test_summary_head_stops_before_first_section(first_run):
    _, _, md = first_run
    head = grade.summary_head(md)
    assert head.startswith("# Stock Scout — run")
    assert "Veto-verdeling:" in head
    assert "## " not in head


# ------------------------------------------- corrupt cache tolerance (§5.5 step 1)

def _corrupt_the_cache(rundir):
    """Two ways a cache entry goes bad in the field, both fatal before the fix:
    a torn/truncated write and an entry that lost its "ticker"."""
    (rundir / "cache" / "BBB.json").write_text('{"ticker": "BBB", "annu',
                                               encoding="utf-8")
    entry = json.loads((rundir / "cache" / "CCC.json").read_text(encoding="utf-8"))
    entry.pop("ticker")
    (rundir / "cache" / "CCC.json").write_text(json.dumps(entry), encoding="utf-8")


def test_load_bundles_survives_corrupt_entries_and_names_them(rundir):
    bundles, universe_n, uncached, unreadable = grade.load_bundles(
        rundir / "universe.csv", rundir / "cache")
    assert (universe_n, uncached, unreadable) == (7, 1, [])
    _corrupt_the_cache(rundir)
    bundles, universe_n, uncached, unreadable = grade.load_bundles(
        rundir / "universe.csv", rundir / "cache")
    assert {b["symbol"] for b in bundles} == {"AAA", "FLGX", "PHIA.AS", "VETX"}
    assert (universe_n, uncached) == (7, 1)       # MISS is still merely uncached
    assert [u["symbol"] for u in unreadable] == ["BBB", "CCC"]
    assert "corrupte JSON" in unreadable[0]["reason"]
    assert "ticker" in unreadable[1]["reason"]


def test_run_completes_and_reports_corrupt_cache_entries(rundir, capsys):
    _corrupt_the_cache(rundir)
    assert grade.main(["--date", RUN_DATE]) == 0   # one bad file is never fatal
    doc = json.loads((rundir / "reports" / f"scout-grades-{RUN_DATE}.json")
                     .read_text(encoding="utf-8"))
    md = (rundir / "reports" / f"scout-run-{RUN_DATE}.md").read_text(encoding="utf-8")
    assert {r["symbol"] for r in doc["names"]} == {"AAA", "FLGX", "PHIA.AS", "VETX"}
    assert doc["universe"] == 7                    # the universe is unchanged...
    assert "niet in cache 1 · onleesbaar in cache 2" in md      # ...and both counted
    assert "- BBB — corrupte JSON" in md           # symbol + reason, never swallowed
    assert "- CCC — ontbrekend veld 'ticker'" in md
    assert "BBB" in capsys.readouterr().err        # and the operator sees it on stderr


# ------------------------------------------------- veto breakdown by sub-reason (§5.5)

def _veto_row(symbol, **kw):
    """A vetoed §3.3 row whose reason string comes from scoring.veto_check itself —
    the grouping must work off the real wording, never a copy of it."""
    base = dict(net_debt_to_ebitda=None, ebitda=None, net_debt=None, credit_loss=None,
                ocf=None, share_trend_pct=None, share_class=False,
                annual_all_negative=False, ttm_owner_fcf=None, roic_pct=None,
                revenue_growth_pct=None)
    veto, _ = scoring.veto_check(**(base | kw))
    assert veto["vetoed"], "fixture must actually trigger a veto"
    return {"symbol": symbol, "grade": "VETOED", "veto": veto}


def test_veto_breakdown_splits_the_two_leverage_branches():
    scored = [
        _veto_row("LEV1", net_debt_to_ebitda=6.1),
        _veto_row("LEV2", net_debt_to_ebitda=4.4),          # same branch, other value
        _veto_row("LEV3", ebitda=0.0, net_debt=1e9),        # the OTHER leverage branch
        _veto_row("CFQ1", ocf=1e8, credit_loss=2.8e7),
        _veto_row("CFQ2", ocf=1e8, credit_loss=7.7e7),      # same branch, other value
        {"symbol": "OK", "grade": "B", "veto": {"vetoed": False, "reason": "", "penalty": 0}},
    ]
    lines = grade._veto_breakdown(scored)
    assert lines[0] == "Veto-verdeling:"
    assert "- leverage veto: 3" in lines             # family rollup
    subs = [ln for ln in lines if ln.startswith("  - ")]
    assert len(subs) == 2                            # msg-10's split, not one bucket
    assert any("net debt/EBITDA" in s and s.endswith(": 2") for s in subs)
    assert any("EBITDA <= 0" in s and s.endswith(": 1") for s in subs)
    # Different measured percentages collapse onto ONE cash-flow-quality sub-reason.
    assert "- cash-flow quality: 2" in lines


def test_canonical_veto_reason_elides_measurements_keeps_thresholds():
    canon = grade.canonical_veto_reason
    assert canon("leverage veto: net debt/EBITDA 6.1 > 4.0") == \
        canon("leverage veto: net debt/EBITDA 12.9 > 4.0")
    assert "> 4.0" in canon("leverage veto: net debt/EBITDA 6.1 > 4.0")
    assert canon("leverage veto: EBITDA <= 0 while carrying net debt") != \
        canon("leverage veto: net debt/EBITDA 6.1 > 4.0")
    assert canon("dilution veto: shares +909.0%/yr (>20%/yr)") == \
        canon("dilution veto: shares +21.4%/yr (>20%/yr)")
    assert canon("") == "veto zonder opgegeven reden"


def test_report_md_shows_the_leverage_split(rundir):
    doc = {"run_date": RUN_DATE, "version": grade.VERSION, "universe": 3, "graded": 0,
           "vetoed": 2, "insufficient": 0, "formation": None,
           "names": [_veto_row("LEV1", net_debt_to_ebitda=6.1),
                     _veto_row("LEV2", ebitda=-1.0, net_debt=1e9)]}
    for row in doc["names"]:
        row.update(composite=None, pillars={}, flags=[], tier="Core", name=row["symbol"])
    md = grade.render_report(doc, [], uncached=0, formation_updated=False)
    assert "- leverage veto: 2" in md
    assert md.count("\n  - ") == 2


# --------------------------------------------------------------- --date validation

def test_bad_date_is_rejected_before_anything_is_written(rundir, capsys):
    for bad in ("30-07-2026", "2026-7-30", "20260730", "2026-02-31", "vandaag"):
        with pytest.raises(SystemExit) as excinfo:
            grade.main(["--date", bad])
        assert excinfo.value.code == 2                 # argparse usage error
        assert "--date" in capsys.readouterr().err
    assert not (rundir / "reports").exists()           # no half-run left behind
    assert not (rundir / "formation-state.json").exists()


def test_iso_date_accepts_and_normalizes_a_real_iso_date():
    assert grade.iso_date(" 2026-07-30 ") == "2026-07-30"
    assert grade.iso_date("2024-02-29") == "2024-02-29"    # a real leap day passes
    with pytest.raises(argparse.ArgumentTypeError):
        grade.iso_date("2026-02-29")                       # right shape, no such day


def test_newest_datasheet_picked_by_date(tmp_path):
    assert grade.newest_datasheet(tmp_path) is None
    (tmp_path / "datasheet-2026-07-29.html").write_text("a", encoding="utf-8")
    (tmp_path / "datasheet-2026-07-30.html").write_text("b", encoding="utf-8")
    (tmp_path / "datasheet-junk.html").write_text("c", encoding="utf-8")
    assert grade.newest_datasheet(tmp_path).name == "datasheet-2026-07-30.html"
