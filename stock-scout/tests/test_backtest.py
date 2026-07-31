"""Offline tests for the backtest harnesses (RECONSTRUCTION.md §5.10, §5.11):
NAV arithmetic incl. the cost drag, delist exits, band-cohort bookkeeping, total-return
(adjusted-close) marking across a split, the bt_cache round-trip for a sanitized symbol,
the owner-mode hold-a-winner scenario (msg 47 'ontsla je beste werknemer'), the
walk-forward verdict structure, quality cohorts, and one synthetic-facts end-to-end
run through the shared decision layer. Injected scored rows + synthetic companyfacts
only — no network, no real caches."""
from __future__ import annotations

import json

import pandas as pd
import pytest

import backtest
import backtest3
import bt_fetch
import formation
import pit
import scoring

# ------------------------------------------------------------ injected-row helpers

T = ["2024-03-28", "2024-06-28", "2024-09-27", "2024-12-27"]   # one tick per quarter


def row(symbol, composite, quality=None, v=50.0, grade="B", vetoed=False, reason=""):
    """Minimal §3.3 scored row: what simulate (composite) and formation.update
    (quality_score, pillars.v, veto) actually consume."""
    return {"symbol": symbol, "grade": "VETOED" if vetoed else grade,
            "composite": None if vetoed else composite,
            "quality_score": None if vetoed else (quality if quality is not None
                                                  else composite),
            "pillars": {"v": v, "q": None, "g": None, "d": None, "m": None},
            "veto": {"vetoed": vetoed, "reason": reason, "penalty": 0}}


def grid_of(path_by_symbol):
    """{symbol: [px per tick]} -> a LEGACY §3.6 weekly grid (plain floats, one value for
    both price fields). Kept deliberately: these tests double as the backward-compatibility
    proof that pre-split-safe caches still load and simulate."""
    return {sym: {day: px for day, px in zip(T, path) if px is not None}
            for sym, path in path_by_symbol.items()}


def bars_of(raw_by_symbol, adj_by_symbol=None):
    """{symbol: [raw px per tick]} (+ optional adjusted path) -> the current §3.6 grid
    shape: {"YYYY-MM-DD": {"close": raw, "adj_close": adjusted}}."""
    adj_by_symbol = adj_by_symbol or raw_by_symbol
    return {sym: {day: {"close": raw, "adj_close": adj}
                  for day, raw, adj in zip(T, path, adj_by_symbol[sym])
                  if raw is not None}
            for sym, path in raw_by_symbol.items()}


# ------------------------------------------------- NAV arithmetic + cost drag (§5.10)

def test_nav_arithmetic_with_cost_drag_and_drift_aware_turnover():
    # X: +10% then +20%; Y: +10% then -10%. Same top-2 both ticks; after the first
    # (+10%, +10%) period the drifted weights are still 50/50 -> zero turnover at T1,
    # so only the initial 10 bp buy-in cost drags: NAV = 0.999 * 1.10 * 1.05.
    prices = grid_of({"X": [100, 110, 132], "Y": [100, 110, 99]})
    scored = {t: [row("X", 90), row("Y", 80)] for t in T[:3]}
    res = backtest.simulate(scored, prices, T[:3], top_n=2, cost_bp=10.0)
    assert res["turnover_pct"] == pytest.approx([100.0, 0.0])
    assert res["nav"][T[0]] == 1.0
    assert res["nav"][T[1]] == pytest.approx(0.999 * 1.10)
    assert res["final_nav"] == pytest.approx(0.999 * 1.10 * 1.05)
    assert res["avg_turnover_pct"] == pytest.approx(0.0)      # initial buy-in excluded
    zero_cost = backtest.simulate(scored, prices, T[:3], top_n=2, cost_bp=0.0)
    assert zero_cost["final_nav"] == pytest.approx(1.10 * 1.05)


def test_partial_rotation_charges_cost_on_the_traded_weight_only():
    # T1 swaps Y (drifted to 0.5) for Z: turnover = |0-0.5| + |0.5-0| = 1.0.
    prices = grid_of({"X": [100, 100, 100], "Y": [100, 100, 100], "Z": [100, 100, 100]})
    scored = {T[0]: [row("X", 90), row("Y", 80), row("Z", 10)],
              T[1]: [row("X", 90), row("Z", 80), row("Y", 10)],
              T[2]: [row("X", 90), row("Z", 80), row("Y", 10)]}
    res = backtest.simulate(scored, prices, T[:3], top_n=2, cost_bp=10.0)
    assert res["turnover_pct"] == pytest.approx([100.0, 100.0])
    assert res["final_nav"] == pytest.approx(0.999 * (1 - 0.001 * 1.0))


# ------------------------------------------- raw vs adjusted marking (§3.6, §5.10)

def test_returns_and_nav_use_adjusted_closes_so_a_split_is_not_a_crash():
    # X splits 2:1 between T1 and T2: the raw close halves (110 -> 55) while the adjusted
    # series runs on. Total-return math must read adj_close (0% over the split), never the
    # raw close (-50%) — the raw close belongs to share-count math only (market cap).
    prices = bars_of({"X": [100.0, 110.0, 55.0]}, {"X": [50.0, 55.0, 55.0]})
    assert backtest.fwd_return(prices, "X", T[0], T[1]) == pytest.approx(0.10)
    assert backtest.fwd_return(prices, "X", T[1], T[2]) == pytest.approx(0.0)
    assert pit.price_at(prices, "X", T[2]) == 55.0            # raw, for the market cap
    assert pit.price_at(prices, "X", T[1]) == 110.0
    scored = {t: [row("X", 90)] for t in T[:3]}
    res = backtest.simulate(scored, prices, T[:3], top_n=1, cost_bp=0.0)
    assert res["final_nav"] == pytest.approx(1.10)            # not 1.10 * 0.5
    assert not backtest.degraded_price_symbols(prices)


def test_benchmark_track_and_degradation_reporting_follow_the_same_rule():
    prices = bars_of({"SPY": [100.0, 110.0, 55.0]}, {"SPY": [50.0, 55.0, 55.0]})
    track = backtest.spy_track(prices, T[:3])
    assert track[T[1]] == pytest.approx(1.10) and track[T[2]] == pytest.approx(1.10)
    # A legacy float grid still simulates, but every reader is told it is contaminated.
    legacy = grid_of({"SPY": [100.0, 110.0, 121.0]})
    assert backtest.spy_track(legacy, T[:3])[T[2]] == pytest.approx(1.21)
    assert backtest.degraded_price_symbols(legacy) == ["SPY"]
    assert any("ruwe close" in d for d in backtest.disclosures(10.0, ["SPY"]))
    assert not any("ruwe close" in d for d in backtest.disclosures(10.0))


# ----------------------------------------------------------------- delist exit (§5.10)

def test_delisted_name_exits_at_last_price_and_is_never_reselected():
    # Z's series ends mid-quarter at 50 (bought at 100): the T0->T1 leg books -50%,
    # at T1 Z is dead -> out of the pool, sold from the drifted 1/3 weight.
    prices = grid_of({"X": [100, 100, 100], "Z": [100, None, None]})
    prices["Z"]["2024-05-10"] = 50.0                    # last bar, mid-quarter
    scored = {t: [row("X", 90), row("Z", 80)] for t in T[:3]}
    res = backtest.simulate(scored, prices, T[:3], top_n=2, cost_bp=10.0)
    assert not backtest.alive(prices, "Z", T[1])
    log = res["tick_log"]
    assert log[0]["held"] == ["X", "Z"] and log[0]["pool"] == 2
    assert log[1]["held"] == ["X"] and log[1]["pool"] == 1
    assert res["nav"][T[1]] == pytest.approx(0.999 * 0.75)
    # Selling the dead 1/3 and topping X up to 1.0 trades 2/3 of NAV.
    assert res["turnover_pct"][1] == pytest.approx(100.0 * 2.0 / 3.0)
    assert res["final_nav"] == pytest.approx(0.999 * 0.75 * (1 - 0.001 * 2.0 / 3.0))


# --------------------------------------------------------- band cohorts (§5.10, msg 44)

def test_band_cohort_bookkeeping_counts_name_quarters_and_mean_returns():
    prices = grid_of({"A1": [100, 110, 132], "F1": [100, 100, 100],
                      "V1": [100, 90, 81], "I1": [100, 100, 100]})
    scored = {t: [row("A1", 90, grade="A"), row("F1", 20, grade="F"),
                  row("V1", None, vetoed=True, reason="leverage veto: x"),
                  {**row("I1", None), "grade": "INSUFFICIENT", "composite": None}]
              for t in T[:3]}
    bands = backtest.band_cohorts(scored, prices, T[:3])
    assert bands["A"] == {"name_quarters": 2,
                          "mean_quarter_return_pct": pytest.approx(15.0)}
    assert bands["F"] == {"name_quarters": 2, "mean_quarter_return_pct": pytest.approx(0.0)}
    assert bands["VETOED"] == {"name_quarters": 2,
                               "mean_quarter_return_pct": pytest.approx(-10.0)}
    assert bands["B"]["name_quarters"] == 0
    assert bands["B"]["mean_quarter_return_pct"] is None
    assert set(bands) == set(backtest.BANDS)            # INSUFFICIENT never a cohort


# ------------------------------------- owner-mode vs plain rotation (§5.11, msg 47)

def _msg47_fixture():
    """The 'ontsla je beste werknemer' scenario: W rallies (+30/+31/+18%), its
    composite sinks below the top-2 cut (v2 rotates it out at T1) while its quality
    rank stays #1 (v3 holds — rank never crosses the exit threshold)."""
    prices = grid_of({"W": [100, 130, 170, 200], "R1": [100.0] * 4,
                      "R2": [100.0] * 4, "R3": [100.0] * 4})
    scored = {T[0]: [row("W", 90, quality=90), row("R1", 80, quality=80),
                     row("R2", 70, quality=70), row("R3", 60, quality=60)]}
    for t in T[1:]:
        scored[t] = [row("W", 60, quality=88), row("R1", 50, quality=80),
                     row("R2", 90, quality=60), row("R3", 85, quality=55)]
    return scored, prices


def test_owner_mode_holds_the_winner_the_plain_policy_rotates_out():
    scored, prices = _msg47_fixture()
    v2 = backtest.simulate(scored, prices, T, top_n=2, cost_bp=10.0)
    v3 = backtest3.simulate_owner(scored, prices, T, top_n=2, cost_bp=10.0)
    # v2 fires its best employee at T1 for getting a raise.
    assert v2["tick_log"][0]["held"] == ["R1", "W"]
    assert v2["tick_log"][1]["held"] == ["R2", "R3"]
    assert "W" not in v2["tick_log"][3]["held"]
    # v3 seats W at bootstrap and never lets go (rank 1 <= exit rank 40 throughout).
    assert all("W" in entry["held"] for entry in v3["holdings_log"])
    assert {m["symbol"] for m in v3["state"]["squad"]} == {"R1", "W"}
    assert [t["symbol"] for t in v3["state"]["transfers"]] == ["W", "R1"]  # bootstrap only
    # Holding the compounder wins: v3 rides W's rally, v2 sold at 130.
    assert v3["final_nav"] > v2["final_nav"]


def test_owner_mode_turnover_below_plain_policy_in_the_rotation_scenario():
    scored, prices = _msg47_fixture()
    v2 = backtest.simulate(scored, prices, T, top_n=2, cost_bp=10.0)
    v3 = backtest3.simulate_owner(scored, prices, T, top_n=2, cost_bp=10.0)
    assert v3["turnover_pct"][1:] == pytest.approx([0.0, 0.0])
    assert v2["turnover_pct"][1] == pytest.approx(200.0)     # full T1 swap, two-sided
    assert v3["avg_turnover_pct"] < v2["avg_turnover_pct"]


def test_owner_mode_exits_on_veto_and_delist_but_not_on_price():
    prices = grid_of({"W": [100, 130, 170, 200], "R1": [100, 100, None, None],
                      "R2": [100.0] * 4})
    prices["R1"]["2024-08-02"] = 80.0                        # R1 delists mid-Q3
    scored = {T[0]: [row("W", 90), row("R1", 80), row("R2", 70)]}
    for t in T[1:]:
        scored[t] = [row("W", 90), row("R2", 70),
                     row("R1", 80, vetoed=True, reason="leverage veto: 5.1 > 4.0")]
    res = backtest3.simulate_owner(scored, prices, T, top_n=2, cost_bp=0.0)
    assert res["holdings_log"][0]["held"] == ["R1", "W"]
    # The veto bites at T1: R1 is out and never returns. (Whether the freed slot is
    # refilled that same tick is formation.py's persistence rule — a bench name with its
    # two quarters of evidence may take it — not this test's subject.)
    assert all("R1" not in entry["held"] for entry in res["holdings_log"][1:])
    reasons = " ".join(t["reason"] for t in res["state"]["transfers"])
    assert "veto" in reasons
    assert all("W" in entry["held"] for entry in res["holdings_log"])


def test_owner_mode_delisted_squad_member_is_force_exited():
    prices = grid_of({"W": [100.0] * 4, "D": [100, 100, None, None]})
    prices["D"]["2024-08-02"] = 60.0                         # D dies before T2
    scored = {t: [row("W", 90), row("D", 80)] for t in T}
    res = backtest3.simulate_owner(scored, prices, T, top_n=2, cost_bp=0.0)
    assert res["holdings_log"][1]["held"] == ["D", "W"]
    assert res["holdings_log"][2]["held"] == ["W"]
    assert any(t["reason"].startswith("eruit — delist")
               for t in res["state"]["transfers"])
    # The T1->T2 leg books D's exit at its last price (60): 0.5 + 0.5*0.6 = 0.80.
    assert res["nav"][T[2]] == pytest.approx(0.80)


# --------------------------------------------------- walk-forward harness (§5.11)

WF_TICKS = ["2022-03-25", "2022-06-24", "2022-09-30", "2022-12-30",     # half A
            "2024-03-29", "2024-06-28", "2024-09-27", "2024-12-27"]     # half B


def _wf_fixture():
    syms = ["N1", "N2", "N3", "N4", "N5"]
    prices = {s: {} for s in syms}
    prices["SPY"] = {}
    for i, tick in enumerate(WF_TICKS):
        prices["SPY"][tick] = 100.0 * 1.02 ** i
        for j, s in enumerate(syms):
            prices[s][tick] = 100.0 * (1.05 if j == 0 else 1.01) ** i
    scored = {t: [row(s, 90 - 10 * j, quality=90 - 10 * j)
                  for j, s in enumerate(syms)] for t in WF_TICKS}
    return scored, prices


def test_walk_forward_returns_the_pre_registered_verdict_structure():
    scored, prices = _wf_fixture()
    result = backtest3.walk_forward(scored, prices, WF_TICKS, top_n=5, cost_bp=10.0)
    assert [len(result["halves"][h]["ticks"]) for h in ("A", "B")] == [4, 4]
    assert len(result["directions"]) == 2
    for d, (cal, blind) in zip(result["directions"], (("A", "B"), ("B", "A"))):
        assert (d["calibrate_half"], d["blind_half"]) == (cal, blind)
        assert len(d["grid"]) == 18                          # 3 x 3 x 2 combos
        assert all({"gate_pctl", "persistence", "exit_rank", "annualized_pct",
                    "avg_turnover_pct", "meets_criterion"} <= set(g) for g in d["grid"])
        assert d["chosen"] in [{k: g[k] for k in ("gate_pctl", "persistence",
                                                  "exit_rank")} for g in d["grid"]]
        assert set(d["blind"]) == {"v3", "v2", "pool", "spy"}
        for key in ("v3", "v2", "pool"):
            assert d["blind"][key]["annualized_pct"] is not None
        assert set(d["criterion"]) == {"beats_pool", "lower_turnover_than_v2", "met"}
        assert d["criterion"]["met"] == (d["criterion"]["beats_pool"]
                                         and d["criterion"]["lower_turnover_than_v2"])
    json.dumps(result, allow_nan=False)                      # report-ready (§5.11)


def test_walk_forward_restores_formations_frozen_constants():
    scored, prices = _wf_fixture()
    backtest3.walk_forward(scored, prices, WF_TICKS, top_n=5,
                           cost_bp=10.0, calibrate_halves=("A",))
    assert formation.SLOTS == scoring.SLOTS
    assert formation.GATE_V_PCTL == scoring.GATE_V_PCTL
    assert formation.PERSISTENCE_QUARTERS == scoring.PERSISTENCE_QUARTERS
    assert formation.EXIT_RANK == scoring.EXIT_RANK


def test_quality_cohorts_rank_buckets_and_cumulative_returns():
    scored, prices = _wf_fixture()                           # 5 names -> all in 1-15
    result = backtest3.quality_cohorts(scored, prices, WF_TICKS)
    top = result["buckets"]["1-15"]
    # Per in-half period the equal-weight top bucket returns (5% + 4x1%)/5 = 1.8%;
    # 3 periods per half (the cross-half gap pair belongs to half A).
    assert top["B"] == pytest.approx(100.0 * (1.018 ** 3 - 1.0))
    assert top["whole"] == pytest.approx(100.0 * (1.018 ** 7 - 1.0))
    assert result["buckets"]["16-50"] == {"A": None, "B": None, "whole": None}
    assert result["periods"]["1-15"]["whole"] == 7
    assert "Rang 1-15" in backtest3.render_cohorts_report(result)


# ---------------------------------------- bt_cache round-trip (§3.6, §5.10 loader)

def _write_cache(tmp_path, symbol, *, annotate=True, legacy_prices=False):
    """Write one facts + one prices file exactly as bt_fetch does (filename sanitized,
    true symbol inside), or in the pre-fix legacy shapes."""
    facts_dir, prices_dir = tmp_path / "bt" / "facts", tmp_path / "bt" / "prices"
    facts_dir.mkdir(parents=True, exist_ok=True)
    prices_dir.mkdir(parents=True, exist_ok=True)
    stem = pit.cache_stem(symbol)
    payload = _facts_for(1.0)
    if annotate:
        payload[pit.SYMBOL_KEY] = symbol
    (facts_dir / f"{stem}.json").write_text(json.dumps(payload), encoding="utf-8")
    if legacy_prices:
        bars = {"2024-03-28": 50.0, "2024-06-28": 55.0}          # flat floats, no symbol
    else:
        frame = pd.DataFrame({"close": [100.0, 110.0], "adj_close": [50.0, 55.0]},
                             index=pd.to_datetime(["2024-03-28", "2024-06-28"], utc=True))
        bars = bt_fetch.prices_payload(frame, "2020-01-01", symbol)
    (prices_dir / f"{stem}.json").write_text(json.dumps(bars), encoding="utf-8")
    universe = tmp_path / "universe.csv"
    universe.write_text("symbol,name,sector,industry\n"
                        f"{symbol},Berkshire Hathaway,Financials,Insurance\n",
                        encoding="utf-8")
    return tmp_path / "bt", universe


def test_sanitized_symbol_round_trips_from_cache_files_back_to_its_universe_meta(tmp_path):
    # The writer sanitizes 'BRK/B' -> BRK-B.json. Keying the loaded dicts by the filename
    # stem loses the symbol: the meta lookup misses (sector None -> wrong tier and wrong
    # sector cohort) and every downstream match against the universe symbol fails.
    symbol = "BRK/B"
    bt_dir, universe = _write_cache(tmp_path, symbol)
    assert (bt_dir / "facts" / "BRK-B.json").exists()
    facts, prices, meta, _splits = backtest.load_bt_cache(bt_dir, universe)
    assert set(facts) == {symbol} and set(prices) == {symbol}
    assert meta[symbol]["sector"] == "Financials"
    assert pit.price_at(prices, symbol, "2024-06-28") == 110.0
    assert pit.price_at(prices, symbol, "2024-06-28", "adj_close") == 55.0
    bundle = pit.as_of_bundle(facts[symbol], symbol, meta[symbol], "2024-06-28", prices)
    assert bundle["sector"] == "Financials"           # the tier/cohort input survives
    assert bundle["market_cap"] == pytest.approx(1_000_000.0 * 110.0)


def test_legacy_cache_files_resolve_through_the_universe_sanitized_name_map(tmp_path):
    # Files written before the in-payload symbol: the loader reverses the sanitization via
    # universe.csv, so an old bt_cache keeps working (its grid is flagged degraded).
    symbol = "BRK/B"
    bt_dir, universe = _write_cache(tmp_path, symbol, annotate=False, legacy_prices=True)
    facts, prices, meta, _splits = backtest.load_bt_cache(bt_dir, universe)
    assert set(facts) == {symbol} and set(prices) == {symbol}
    assert meta[symbol]["sector"] == "Financials"
    assert backtest.degraded_price_symbols(prices) == [symbol]
    # With no universe row to reverse it, the stem is all that is left — and it is honest.
    empty = tmp_path / "nothing.csv"
    facts, prices, _, _ = backtest.load_bt_cache(bt_dir, empty)
    assert set(facts) == {"BRK-B"} and set(prices) == {"BRK-B"}


# ------------------------------- synthetic facts end-to-end (§5.10, test_pit style)

def dfact(start, end, val, filed):
    return {"start": start, "end": end, "val": val, "form": "10-Q", "filed": filed}


def ifact(end, val, filed):
    return {"end": end, "val": val, "form": "10-Q", "filed": filed}


def _year_flows(year, q, filed_fy):
    start = f"{year}-01-01"
    return [dfact(start, f"{year}-03-31", q, f"{year}-05-01"),
            dfact(start, f"{year}-06-30", 2 * q, f"{year}-08-01"),
            dfact(start, f"{year}-09-30", 3 * q, f"{year}-11-01"),
            dfact(start, f"{year}-12-31", 4 * q, filed_fy)]


def _facts_for(scale):
    """One healthy filer, all flows scaled: FY2021-FY2024 quarterly + annual filings,
    year-end balance instants, a flat share count (the test_pit fixture style)."""
    flows = {"Revenues": 100.0, "OperatingIncomeLoss": 20.0, "GrossProfit": 60.0,
             "NetIncomeLoss": 15.0, "ProfitLoss": 15.0,
             "NetCashProvidedByUsedInOperatingActivities": 30.0,
             "PaymentsToAcquirePropertyPlantAndEquipment": 5.0,
             "ShareBasedCompensation": 2.0,
             "DepreciationDepletionAndAmortization": 6.0}
    instants = {"LongTermDebt": 50.0, "CashAndCashEquivalentsAtCarryingValue": 100.0,
                "Assets": 1000.0, "AssetsCurrent": 400.0, "LiabilitiesCurrent": 200.0,
                "StockholdersEquity": 500.0}
    gaap = {}
    for year in range(2021, 2025):
        filed_fy = f"{year + 1}-02-01"
        for tag, base in flows.items():
            gaap.setdefault(tag, []).extend(
                _year_flows(year, base * scale * (1.0 + 0.05 * (year - 2021)), filed_fy))
        for tag, base in instants.items():
            gaap.setdefault(tag, []).append(ifact(f"{year}-12-31", base * scale, filed_fy))
    shares = [ifact(f"{year}-01-15", 1_000_000.0, f"{year}-01-20")
              for year in range(2021, 2025)]
    payload = {"cik": 1, "entityName": "Synthetic", "facts": {
        "us-gaap": {tag: {"label": tag, "units": {"USD": entries}}
                    for tag, entries in gaap.items()},
        "dei": {"EntityCommonStockSharesOutstanding":
                {"label": "shares", "units": {"shares": shares}}}}}
    return payload


E2E_TICKS = ["2023-03-31", "2023-06-30", "2023-09-29", "2023-12-29", "2024-03-28",
             "2024-06-28", "2024-09-27", "2024-12-27", "2025-03-28"]


def test_end_to_end_synthetic_facts_through_the_shared_decision_layer():
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    facts = {s: _facts_for(scale) for s, scale in zip(symbols, (1.0, 2.0, 3.0, 4.0))}
    prices = {"SPY": {t: 100.0 * 1.02 ** i for i, t in enumerate(E2E_TICKS)}}
    for j, s in enumerate(symbols):
        prices[s] = {t: 50.0 * (1.0 + 0.01 * j) ** i for i, t in enumerate(E2E_TICKS)}
    meta = {s: {"name": s, "sector": "Information Technology", "industry": "Software"}
            for s in symbols}

    result = backtest.run_backtest(facts, prices, meta, start="2023-01-01",
                                   end="2025-06-30", top_n=2, cost_bp=10.0)
    assert result["ticks"] == pit.quarter_ends(prices["SPY"], "2023-01-01", "2025-06-30")
    assert result["quarters"] == 8
    assert len(result["strategy"]["nav"]) == 9
    assert result["strategy"]["final_nav"] > 0
    # All four names grade on every tick (FY2021+FY2022 visible from the first one).
    assert [e["pool"] for e in result["tick_log"]] == [4] * 9
    assert all(len(e["top5"]) == 4 for e in result["tick_log"])
    total = sum(result["bands"][b]["name_quarters"] for b in backtest.BANDS)
    assert total == 4 * 8                                    # 4 names x 8 fwd quarters
    md = backtest.render_report(result)
    assert "Band-cohorten" in md and "PIT-discipline" in md and "Tick-log" in md
    json.dumps(result, allow_nan=False)                      # §5.10 .json contract
    # This fixture runs on a legacy float grid, so the report must own up to it.
    assert result["degraded_price_symbols"] == sorted(["SPY"] + symbols)
    assert any("ruwe close" in d for d in result["disclosures"])
    assert "ruwe close" in md

    # And the same PIT world drives owner-mode + walk-forward unchanged (§5.11).
    scored = backtest.score_ticks(facts, prices, meta, result["ticks"])
    owner = backtest3.simulate_owner(scored, prices, result["ticks"],
                                     top_n=2, cost_bp=10.0)
    assert owner["final_nav"] > 0
    assert owner["state"]["squad"]                            # someone got seated
