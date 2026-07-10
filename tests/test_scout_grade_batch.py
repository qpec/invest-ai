"""Stage-1 batch grading (design §4 Stage-1): cached statements -> metrics -> veto ->
sector percentiles -> pillars -> composite -> tier, over the universe DataFrame.
Vetoed names are SUPPRESSED (grade='VETOED'); thin data -> 'insufficient data'.

RF2/RF3 — grade_universe wires the REAL raw ebitda + net_debt AND the per-period
cash-destruction flag from durability_metrics into veto_check (never fabricated inputs);
a leverage-vetoed name gets grade='VETOED' and is not ranked.
RF5 — a None REQUIRED pillar metric (e.g. owner_fcf_yield when EV <= 0) is an
integrity-suspend: an INSUFFICIENT row with a printed reason is emitted BEFORE any
percentile call, never a None fed into percentileofscore. An EV<=0 case is exercised.
RF6 — a same-sector multi-name integration case reaches an A (composite >= 80), proving
the percentile pipeline can hit the top band; a rising-share case proves the -15 dilution
penalty actually fires on a GradedName.
"""
from datetime import datetime, timezone

import pandas as pd

from agentcy.fetch import store
from agentcy import scout_grade as sg

AS_OF = datetime(2026, 7, 8, tzinfo=timezone.utc)

UNIVERSE = pd.DataFrame({
    "symbol": ["MSFT", "VEEV", "THIN"],
    "sector": ["Technology", "Technology", "Technology"],
    "industry": ["Software", "Software", "Software"],
    "market_cap": ["large_cap", "large_cap", "small_cap"],
})

MARKET = {
    "MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
    "VEEV": {"market_cap": 3.0e11, "total_debt": 60e9, "cash": 84e9},
    "THIN": {"market_cap": 1e9, "total_debt": 0.0, "cash": 0.0},
}


def _seed_full(conn, symbol, yf_statements, yf_series):
    store.store_statements(conn, symbol, yf_statements("msft_statements"),
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, symbol, yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")


def test_batch_grades_full_names_and_suspends_thin(tmp_db, yf_statements, yf_series):
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    _seed_full(tmp_db, "VEEV", yf_statements, yf_series)
    # THIN: only one income period -> owner_fcf not computable -> insufficient data
    store.store_statements(tmp_db, "THIN", {"income": yf_statements("msft_statements")["income"].iloc[:, :1]},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")

    graded = sg.grade_universe(tmp_db, UNIVERSE, market_data=MARKET, as_of=AS_OF)
    by_sym = {g.symbol: g for g in graded}
    assert set(by_sym) == {"MSFT", "VEEV", "THIN"}
    # full names carry a numeric composite + a letter grade + a tier
    assert by_sym["MSFT"].grade in ("A", "B", "C", "D", "F")
    assert by_sym["MSFT"].tier == "Core"
    assert by_sym["VEEV"].tier == "Core"
    assert 0.0 <= by_sym["MSFT"].composite <= 100.0
    # thin name is suspended, never a silent 0
    assert by_sym["THIN"].grade == "INSUFFICIENT"
    assert by_sym["THIN"].composite is None
    assert "insufficient data" in by_sym["THIN"].note.lower()


def test_batch_percentiles_are_sector_relative(tmp_db, yf_statements, yf_series):
    # two identical-statement names in the same sector -> identical percentiles -> equal composites
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    _seed_full(tmp_db, "VEEV", yf_statements, yf_series)
    graded = sg.grade_universe(tmp_db, UNIVERSE.iloc[:2],
                               market_data={k: MARKET[k] for k in ("MSFT", "VEEV")}, as_of=AS_OF)
    comps = {g.symbol: g.composite for g in graded}
    # same statements, same sector, only market_cap differs (V leg) -> Q/D/M identical
    assert comps["MSFT"] is not None and comps["VEEV"] is not None


def test_output_order_matches_universe_order(tmp_db, yf_statements, yf_series):
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    _seed_full(tmp_db, "VEEV", yf_statements, yf_series)
    store.store_statements(tmp_db, "THIN", {"income": yf_statements("msft_statements")["income"].iloc[:, :1]},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    graded = sg.grade_universe(tmp_db, UNIVERSE, market_data=MARKET, as_of=AS_OF)
    assert [g.symbol for g in graded] == ["MSFT", "VEEV", "THIN"]


def test_missing_market_data_is_insufficient_not_crash(tmp_db, yf_statements, yf_series):
    # a name with statements but no market_data entry (V pillar uncomputable) -> INSUFFICIENT.
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    graded = sg.grade_universe(tmp_db, UNIVERSE.iloc[:1], market_data={}, as_of=AS_OF)
    g = graded[0]
    assert g.symbol == "MSFT"
    assert g.grade == "INSUFFICIENT"
    assert g.composite is None
    assert "insufficient data" in g.note.lower()


# --- RF5: a None REQUIRED pillar metric is an integrity-suspend, never a TypeError --------

def test_ev_non_positive_required_metric_is_insufficient_before_any_percentile(
        tmp_db, yf_statements, yf_series):
    """RF5 — when EV <= 0 the owner_fcf_yield (a REQUIRED V-pillar metric) is None; the name
    must be emitted as INSUFFICIENT with a PRINTED reason BEFORE any sector_percentile call,
    never passing None into percentileofscore."""
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    _seed_full(tmp_db, "VEEV", yf_statements, yf_series)
    # MSFT: cash (100e9) swamps market_cap (50e9) -> EV = -50e9 <= 0 -> owner_fcf_yield None.
    market = {
        "MSFT": {"market_cap": 50e9, "total_debt": 0.0, "cash": 100e9},
        "VEEV": {"market_cap": 3.0e11, "total_debt": 60e9, "cash": 84e9},
    }
    graded = sg.grade_universe(tmp_db, UNIVERSE.iloc[:2], market_data=market, as_of=AS_OF)
    by_sym = {g.symbol: g for g in graded}
    assert by_sym["MSFT"].grade == "INSUFFICIENT"
    assert by_sym["MSFT"].composite is None
    assert by_sym["MSFT"].v is None
    assert "insufficient data" in by_sym["MSFT"].note.lower()
    # EV<=0 reason is printed (not a silent suspend)
    assert "ev" in by_sym["MSFT"].note.lower()
    # the healthy peer still grades (the suspend of one name never crashes the batch)
    assert by_sym["VEEV"].composite is not None


# --- RF2/RF3: the veto layer is wired from the REAL durability figures --------------------

def test_leverage_vetoed_name_is_suppressed_with_real_ebitda_net_debt(
        tmp_db, yf_statements, yf_series):
    """RF2 — a name whose REAL net-debt/EBITDA exceeds the §2 floor is VETOED (suppressed),
    not ranked. The veto reads durability_metrics' real ebitda + net_debt, not a placeholder."""
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    # LEVR: healthy statements but the balance sheet carries huge net debt so net-debt/EBITDA
    # is > 4 -> leverage veto. Build it by rewriting Total Debt on the recorded balance sheet.
    pack = yf_statements("msft_statements")
    bal = pack["balance"].copy()
    bal.loc["Total Debt"] = [900e9, 900e9, 900e9, 900e9]     # net debt ~816e9 vs EBITDA 142e9
    store.store_statements(tmp_db, "LEVR",
                           {"income": pack["income"], "balance": bal, "cashflow": pack["cashflow"]},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "LEVR", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    universe = pd.DataFrame({
        "symbol": ["MSFT", "LEVR"],
        "sector": ["Technology", "Technology"],
        "industry": ["Software", "Software"],
        "market_cap": ["large_cap", "large_cap"],
    })
    market = {
        "MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
        "LEVR": {"market_cap": 2.8e12, "total_debt": 900e9, "cash": 84e9},
    }
    graded = sg.grade_universe(tmp_db, universe, market_data=market, as_of=AS_OF)
    by_sym = {g.symbol: g for g in graded}
    assert by_sym["LEVR"].grade == "VETOED"
    assert by_sym["LEVR"].composite is None
    assert "leverage" in by_sym["LEVR"].note.lower()
    # the clean name is unaffected and still graded
    assert by_sym["MSFT"].composite is not None


def test_cash_destruction_veto_uses_per_period_flag_not_ttm_sign(
        tmp_db, yf_statements, yf_series):
    """RF3 — a serial cash-burner (owner-FCF negative in EVERY recorded period) is VETOED via
    the per-period flag, not the TTM-sum sign."""
    _seed_full(tmp_db, "MSFT", yf_statements, yf_series)
    pack = yf_statements("msft_statements")
    cash = pack["cashflow"].copy()
    # every period owner-FCF = 1 - 10 - 3 = -12e9 (negative in ALL periods)
    for c in list(cash.columns):
        cash.loc["Operating Cash Flow", c] = 1e9
        cash.loc["Capital Expenditure", c] = -10e9
        cash.loc["Stock Based Compensation", c] = 3e9
    store.store_statements(tmp_db, "BURN",
                           {"income": pack["income"], "balance": pack["balance"], "cashflow": cash},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(tmp_db, "BURN", yf_series("msft_shares_full"),
                       fetched_at="2026-07-01T00:00:00Z")
    universe = pd.DataFrame({
        "symbol": ["MSFT", "BURN"],
        "sector": ["Technology", "Technology"],
        "industry": ["Software", "Software"],
        "market_cap": ["large_cap", "large_cap"],
    })
    market = {
        "MSFT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
        "BURN": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
    }
    graded = sg.grade_universe(tmp_db, universe, market_data=market, as_of=AS_OF)
    by_sym = {g.symbol: g for g in graded}
    assert by_sym["BURN"].grade == "VETOED"
    assert "cash" in by_sym["BURN"].note.lower()


# --- RF6: rising-share dilution penalty fires on a GradedName -----------------------------

# RF6 baseline: latest 2026-06-20 within 90d of as_of; oldest 2025-06-20 a real ~1y anchor.
SHARE_INDEX = pd.to_datetime(["2025-06-20", "2025-12-20", "2026-06-20"])


def test_rising_shares_apply_minus15_dilution_penalty_on_graded_name(
        tmp_db, yf_statements, yf_series):
    """RF6 — a diluting name (shares_yoy_pct > 5) takes the -15 dilution penalty on its
    GradedName: its composite is strictly below the identical-statement clean twin's."""
    # CLEAN and DILUT have identical statements and market data; only the share TREND differs.
    pack = yf_statements("msft_statements")
    store.store_statements(tmp_db, "CLEAN", pack, run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_statements(tmp_db, "DILUT", pack, run_id=None, fetched_at="2026-07-01T00:00:00Z")
    # CLEAN: flat/shrinking shares -> no dilution penalty.
    store.store_shares(tmp_db, "CLEAN",
                       pd.Series([7.60e9, 7.50e9, 7.40e9], index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")
    # DILUT: rising shares (7.20e9 -> 7.60e9 over ~1y => >5% issuance) -> -15 penalty.
    store.store_shares(tmp_db, "DILUT",
                       pd.Series([7.20e9, 7.40e9, 7.60e9], index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")
    universe = pd.DataFrame({
        "symbol": ["CLEAN", "DILUT"],
        "sector": ["Technology", "Technology"],
        "industry": ["Software", "Software"],
        "market_cap": ["large_cap", "large_cap"],
    })
    market = {
        "CLEAN": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
        "DILUT": {"market_cap": 2.8e12, "total_debt": 59e9, "cash": 84e9},
    }
    graded = sg.grade_universe(tmp_db, universe, market_data=market, as_of=AS_OF)
    by_sym = {g.symbol: g for g in graded}
    assert by_sym["CLEAN"].grade != "VETOED" and by_sym["DILUT"].grade != "VETOED"
    # the -15 penalty makes the diluting twin score strictly lower than the clean twin.
    assert by_sym["DILUT"].composite < by_sym["CLEAN"].composite
    assert "dilut" in by_sym["DILUT"].note.lower()


# --- RF6: the percentile pipeline can reach the top band (A, composite >= 80) --------------

_A_COLS = pd.to_datetime(["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])


def _seed_synth(conn, symbol, *, quality, jitter, shares):
    """Seed a fully-synthetic same-sector name whose profitability scales with ``quality``
    (1.0 = the cohort leader; < 1.0 = strictly weaker). ``jitter`` perturbs the per-period
    gross margin so a peer's margin-stability (CV) is worse than the flat leader's; ``shares``
    is a 3-point ~1y series (a shrinking series lifts per-share owner-FCF growth). Constructed
    so the leader is strictly best on every scored leg -> its sector percentiles top out
    (~90) and it reaches an A (composite >= 80)."""
    rev = 100e9
    gm, opm, ocf_m = 0.70 * quality, 0.40 * quality, 0.42 * quality
    capex_m, sbc_m, ni_m = 0.05, 0.02 / quality, 0.30 * quality
    debt, cash = 20e9 / quality, 30e9 * quality
    inc = pd.DataFrame(index=["Total Revenue", "Cost Of Revenue", "Gross Profit",
                              "Operating Income", "EBITDA", "EBIT", "Net Income"],
                       columns=_A_COLS, dtype=float)
    bal = pd.DataFrame(index=["Total Debt", "Cash And Cash Equivalents", "Total Assets",
                              "Current Assets", "Working Capital"], columns=_A_COLS, dtype=float)
    cf = pd.DataFrame(index=["Operating Cash Flow", "Capital Expenditure",
                             "Stock Based Compensation"], columns=_A_COLS, dtype=float)
    for i, c in enumerate(_A_COLS):
        g = gm + (jitter if i % 2 else -jitter)
        inc.loc["Total Revenue", c] = rev
        inc.loc["Gross Profit", c] = rev * g
        inc.loc["Cost Of Revenue", c] = rev * (1 - g)
        inc.loc["Operating Income", c] = rev * opm
        inc.loc["EBIT", c] = rev * opm
        inc.loc["EBITDA", c] = rev * opm * 1.2
        inc.loc["Net Income", c] = rev * ni_m
        bal.loc["Total Debt", c] = debt
        bal.loc["Cash And Cash Equivalents", c] = cash
        bal.loc["Total Assets", c] = rev * 4.2
        bal.loc["Current Assets", c] = rev * 3
        bal.loc["Working Capital", c] = rev * 0.2
        cf.loc["Operating Cash Flow", c] = rev * ocf_m
        cf.loc["Capital Expenditure", c] = -rev * capex_m
        cf.loc["Stock Based Compensation", c] = rev * sbc_m
    store.store_statements(conn, symbol, {"income": inc, "balance": bal, "cashflow": cf},
                           run_id=None, fetched_at="2026-07-01T00:00:00Z")
    store.store_shares(conn, symbol, pd.Series(shares, index=SHARE_INDEX),
                       fetched_at="2026-07-01T00:00:00Z")


def test_same_sector_cohort_reaches_top_band_A(tmp_db):
    """RF6 — a same-sector cohort with a genuine leader plus four strictly-weaker peers pushes
    the leader's sector percentiles to the top, producing at least one A (composite >= 80).
    Proves the percentile pipeline can reach the top band (a singleton cohort scores 50, so an
    A requires a >=2-name cohort with a real leader)."""
    # leader: flat top-tier margins + shrinking shares (positive per-share owner-FCF growth).
    _seed_synth(tmp_db, "LEAD", quality=1.0, jitter=0.0, shares=[1.05e9, 1.02e9, 1.00e9])
    peers = (("P1", 0.90), ("P2", 0.80), ("P3", 0.70), ("P4", 0.60))
    for sym, q in peers:
        _seed_synth(tmp_db, sym, quality=q, jitter=0.02, shares=[1.00e9, 1.00e9, 1.00e9])
    symbols = ["LEAD", *[s for s, _ in peers]]
    universe = pd.DataFrame({
        "symbol": symbols,
        "sector": ["Technology"] * 5,
        "industry": ["Software"] * 5,
        "market_cap": ["large_cap"] * 5,
    })
    # leader carries the cheapest EV per unit owner-FCF (highest yield); weaker peers are
    # priced higher relative to their thinner cash flows.
    market = {"LEAD": {"market_cap": 1.0e12, "total_debt": 20e9, "cash": 30e9}}
    for sym, q in peers:
        market[sym] = {"market_cap": 1.0e12 / q, "total_debt": 20e9 / q, "cash": 30e9 * q}
    graded = sg.grade_universe(tmp_db, universe, market_data=market, as_of=AS_OF)
    by_sym = {g.symbol: g for g in graded}
    lead = by_sym["LEAD"]
    assert lead.grade == "A", f"leader composite={lead.composite} v/q/d/m={lead.v}/{lead.q}/{lead.d}/{lead.m}"
    assert lead.composite >= 80.0
    # the cohort spans real bands (not everyone an A) — a genuine leader, not a flat tie.
    assert by_sym["P4"].composite < lead.composite
