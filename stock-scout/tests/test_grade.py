"""Offline tests for grade.py (spec §5.5, §3.3): a synthetic §3.2 cache dir (6 names,
2 sectors, one vetoed, one flagged, one uncached) -> grade.main with --date pinned ->
grades JSON schema (incl. the Owner's Scorecard per graded name), report md sections
(the banded scorecard tables that now lead the report, "hoe je dit leest", the
segregation of NO PRICE/VETOED names, De Formatie, veto breakdown, NL call-out),
formation-state.json creation and same-date idempotence. No network, no real caches."""
from __future__ import annotations

import argparse
import copy
import csv
import json

import pytest

import formation
import grade
import scorecard
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
             "mos", "buffett", "scorecard"}
SCORECARD_KEYS = {"score", "available_max", "pct", "band", "band_meaning", "blocks",
                  "metrics", "why", "consensus", "coverage", "veto", "notes"}


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


# --------------------------------------------------- the Owner's Scorecard on the row

def test_every_graded_name_carries_a_wellformed_scorecard(first_run):
    """§3.3: one absolute card per graded name, and it must be internally consistent —
    blocks summing to the score out of the AVAILABLE maximum, never a silent 0/100."""
    _, doc, _ = first_run
    graded = [r for r in doc["names"] if r["grade"] in grade.GRADE_LETTERS]
    assert len(graded) == 5
    for row in graded:
        card = row["scorecard"]
        assert set(card) == SCORECARD_KEYS
        assert card["band"] in {e["band"] for e in scorecard.BANDS}
        assert set(card["blocks"]) == set(scorecard.BLOCKS)
        assert set(card["metrics"]) == set(scorecard.ANCHORS)
        assert card["available_max"] == sum(b["max"] for b in card["blocks"].values())
        assert card["score"] == pytest.approx(
            sum(b["points"] for b in card["blocks"].values()), abs=0.05)
        assert card["pct"] == round(100.0 * card["score"] / card["available_max"])
        assert isinstance(card["pct"], int)          # no false precision (§4.4)
        assert card["consensus"]["of"] == len(scorecard.CONSENSUS_LENSES)
        assert card["notes"][-1].startswith("Differences under 5 points")


def test_scorecard_metric_points_are_traceable_to_an_anchor(first_run):
    """Every point must be auditable: the stored points are the §2 ramp of the stored raw
    value between the metric's own two anchors, recomputed here independently."""
    _, doc, _ = first_run
    card = next(r for r in doc["names"] if r["symbol"] == "AAA")["scorecard"]
    for mid, metric in card["metrics"].items():
        anchor = scorecard.ANCHORS[mid]
        if metric["points"] is None:
            assert metric["value"] is None and "not computable" in metric["detail"]
            continue
        frac = ((metric["value"] - anchor["floor"])
                / (anchor["target"] - anchor["floor"]))
        expected = max(0.0, min(1.0, frac)) * anchor["points"]
        assert metric["points"] == pytest.approx(expected, abs=0.05)


def test_vetoed_and_uncardable_names_get_no_scorecard(first_run):
    _, doc, _ = first_run
    vetx = next(r for r in doc["names"] if r["symbol"] == "VETX")
    assert vetx["scorecard"] is None                 # a veto suppresses, it does not rank


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


# -------------------------------------- the report now LEADS with the scorecard (§5.5)

def _section(md: str, heading: str) -> str:
    """The text of one '## ' section, up to the next one."""
    body = md.split(f"\n## {heading}", 1)[1]
    return body.split("\n## ", 1)[0]


def test_report_leads_with_the_scorecard_not_the_composite(first_run):
    _, _, md = first_run
    scorecard_at = md.index("## Scorecard — absolute punten")
    context_at = md.index("## Sectorrelatieve context")
    assert scorecard_at < context_at                 # the interpretable number comes first
    assert md.index("Hoe je dit leest:") < scorecard_at
    assert md.index("### Core") > context_at         # the tier tables are now context


def test_report_main_table_columns_lead_with_score_and_band(first_run):
    _, _, md = first_run
    section = _section(md, "Scorecard — absolute punten")
    header = next(ln for ln in section.splitlines() if ln.startswith("| symbool"))
    cols = [c.strip() for c in header.strip("|").split("|")]
    assert cols == ["symbool", "naam", "score", "band", "consensus", "Q", "P", "S", "St",
                    "flags", "rang in sector (context)"]
    assert "#" not in cols                           # no rank column — §1.2 is the reason
    row = next(ln for ln in section.splitlines() if ln.startswith("| AAA |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[2].startswith("68/100")             # score before everything else
    assert cells[3] == "Strong"
    assert cells[4] == "2/3"                         # consensus n/3
    assert cells[5].endswith("/35") and cells[6].endswith("/25")     # Q, P blocks
    assert cells[7].endswith("/25") and cells[8].endswith("/12")     # S, St blocks
    assert cells[10].startswith("C ")                # grade+composite, last, as context


def test_report_shows_the_reduced_denominator_not_a_silent_hundred(first_run):
    """§4.2: this fixture has no dividend/buyback row, so capital-returned drops out and
    the card is scored out of 97 — the table must say so rather than imply 100."""
    _, doc, md = first_run
    card = next(r for r in doc["names"] if r["symbol"] == "AAA")["scorecard"]
    assert card["available_max"] == 97
    section = _section(md, "Scorecard — absolute punten")
    assert "66.4/97 pt" in section


def test_report_how_to_read_block_states_bands_noise_floor_and_no_price(first_run):
    _, _, md = first_run
    head = md.split("Veto-verdeling:", 1)[0]         # the block sits above the sections...
    assert "Hoe je dit leest:" in head
    assert f"±{scorecard.NOISE_FLOOR:.0f} punten" in head
    assert "Lees banden, geen rangen" in head
    assert "Consensus n/3" in head
    assert "NO PRICE is géén oordeel" in head
    assert "rang in sector" in head
    assert "Hoe je dit leest:" in grade.summary_head(md)    # ...so Telegram gets it too


def test_report_groups_by_band_and_sorts_by_pct_within_the_band(first_run):
    _, doc, md = first_run
    section = _section(md, "Scorecard — absolute punten")
    assert "### Strong 65–79 (5) — Worth the Gate's homework" in section
    assert "### Weak" not in section                 # empty bands are not printed...
    assert "Banden: Exceptional 0 · Strong 5" in md   # ...the header carries the occupancy
    order = [ln.split("|")[1].strip() for ln in section.splitlines()
             if ln.startswith("| ") and not ln.startswith("| symbool")]
    cards = {r["symbol"]: r["scorecard"]["pct"] for r in doc["names"] if r["scorecard"]}
    assert order == sorted(order, key=lambda s: (-cards[s], s))


def test_vetoed_names_are_segregated_from_the_banded_ordering(first_run):
    _, _, md = first_run
    banded = _section(md, "Scorecard — absolute punten")
    unbanded = _section(md, "Zonder band (geen oordeel)")
    assert "VETX" not in banded                      # never mixed into the ordering (§4.3)
    assert "### VETOED (1)" in unbanded
    assert "- VETX — Overlevered Corp. — leverage veto:" in unbanded


def test_a_no_price_name_is_a_quality_profile_and_never_a_verdict(first_run, rundir):
    """§4.1, the single most important honesty rule: without price data the report shows
    the literal NO PRICE band plus the disclaimer, keeps the name out of the bands, and
    never prints an x/100 verdict for it."""
    rundir, doc, _ = first_run
    entry = json.loads((rundir / "cache" / "AAA.json").read_text(encoding="utf-8"))
    bundle = grade.build_bundle(entry) | {"market_cap": None, "yahoo_ev": None,
                                          "price": None}
    card = scorecard.scorecard(bundle)
    assert card["band"] == "NO PRICE"                # the literal band, not a letter

    doc = copy.deepcopy(doc)
    next(r for r in doc["names"] if r["symbol"] == "AAA")["scorecard"] = card
    md = grade.render_report(doc, [], uncached=0, formation_updated=False)
    banded = _section(md, "Scorecard — absolute punten")
    unbanded = _section(md, "Zonder band (geen oordeel)")
    assert "| AAA |" not in banded                   # not sorted next to a verdict
    assert "### NO PRICE (1)" in unbanded
    assert "NOT a verdict" in unbanded               # the §4.1 disclaimer, verbatim
    assert "Quality profile only" in unbanded
    aaa = next(ln for ln in unbanded.splitlines() if ln.startswith("| AAA |"))
    assert "/100" not in aaa                         # points out of what was available...
    assert f"/{card['available_max']} pt" in aaa     # ...never a 0-100 verdict
    assert aaa.split("|")[4].strip() == "NO PRICE"


def test_band_ranges_are_derived_from_the_band_table(monkeypatch):
    assert grade._band_range("Exceptional") == "80–100"
    assert grade._band_range("Strong") == "65–79"
    assert grade._band_range("Pass") == "0–34"
    monkeypatch.setitem(grade.BAND_FLOOR, "Strong", 70)
    assert grade._band_range("Strong") == "70–79"     # genuinely derived, never a copy
    assert grade._band_range("Mixed") == "50–69"


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
