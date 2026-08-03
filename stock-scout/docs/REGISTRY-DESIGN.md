# The Metric Registry, audited — and Registry v2 (PROPOSED)

**Status:** RATIFIED and IMPLEMENTED, 2026-08-03. The owner's ratifying words — *"the
goal is to maintain within the philosophy, use metrics for a richer overview"* — set the
implementation's two constraints: the decision machinery stays frozen (proven: full-
universe bit-identity diff, 1,904 names, 0 differing values), and the new metrics enrich
what the owner READS (registry, packet, site drill-down) rather than what the machine
DECIDES. Composites are display-only accordingly. Shipped: `registry.py` (the v2
arithmetic), a `supplements` stream in `pit.py` (new concepts that can never enter the
frozen statement sections), `thesis.METRICS` at 26 metrics (§4 below said 24 rows; the
shareholder-yield split ships as two metrics and acquisitions as a third, hence 26 keys),
FinanceToolkit in `requirements-research.txt` as the desk-side ratio canon and test
oracle. One §4 amendment made during implementation: the capital-allocation trio is
measured as **% of OCF, not % of market cap** — a market-cap denominator would have made
them quote-derived, which the no-price-triggers rule exists to prevent.

---

## 1. The honest audit

**Are the current 10 metrics sufficient to build a thesis? No — and they were never
meant to be.** The registry was designed as the *trigger vocabulary*: the set of
quantities the weekly monitor can check mechanically, so that a thesis's invalidation
rules are testable rather than vibes. Thesis *building* was always three-legged — the
metrics, the filings text, and the agent's research — and the CROX draft proved the
point: every load-bearing fact in it (the $738m HEYDUDE write-down, tariffs at 160bp of
gross margin, the marketplace reclassification, two manufacturers producing ~73% of
output) came from research, not from any registry metric.

**Are they sufficient to MONITOR a thesis? A good spine, with named blind spots:**

- **One leverage number, no debt nuance.** `net_debt_to_ebitda` alone — no interest
  coverage, no maturity picture. The pipeline already computes interest coverage
  internally (scoring.py's WACC estimate) and does not expose it.
- **Margin level without margin trend.** `gross_margin_pct` is a point; the inversion
  layer computes margin *variability* (MAD) and the registry cannot reference it.
  Operating margin is absent entirely despite 1,834/1,904 coverage in tier 1.
- **No per-share view.** The buyback (`share_count_trend`) and the cash engine
  (`owner_fcf`) are tracked separately; the owner's actual compounding unit — owner FCF
  per share — is not a registry quantity.
- **No working-capital or earnings-quality detail** beyond `accrual_divergence`: no
  inventory turns, no DSO, no cash-vs-effective tax gap.
- **No capital-allocation decomposition.** Buybacks are visible; dividends and — the
  HEYDUDE lesson — *acquisition spend* are not.
- **No segments.** Consolidated numbers could not see HEYDUDE shrinking inside a
  growing Crocs; the core-brand trigger had to be an event question instead of
  arithmetic.

**The binding constraint is data, not definitions.** Measured on the real universe: the
bulk export (tier 1) carries only **19 distinct tags**, zero of 1,904 names have all 10
current metrics, and `net_debt_to_ebitda` had 0% tier-1 coverage until the enrichment
chain (enrich.py) added live companyfacts as tier 2. Widening the registry without
widening the data would just mint more `n/a` — and `record` already refuses a trigger on
an uncomputable metric, so the metrics and the data must move together.

## 2. The data reality, measured

| Source | What it carries | Segments? | PIT-safe? |
|---|---|---|---|
| Tier 1 — bulk CSV export | **19 tags** (our own export selected them; the full raw companyfacts JSONs it was cut from live in `bt_cache/facts/` on the desk box) | no | yes (`filed` kept) |
| Tier 2 — live companyfacts (enrich.py) | ~400–650 tags per name, every undimensioned us-gaap/dei concept | **no** (companyfacts drops dimensions) | yes |
| SEC DERA FSDS quarterly zips | every as-filed statement fact, all filers, `adsh` + `filed` | partially (via `pre`/`num` detail) | yes |
| Full filing XBRL (edgartools) | everything, **including dimensioned facts** — segment revenue/operating income | **yes** | yes |
| yfinance (tier 3, cherry) | vendor aggregates | n/a | **no — display-only, never scored** |

## 3. The DeepGit sweep (journal)

Method: four search lenses over GitHub via web search (ratio engines · deeper XBRL
extraction · bulk datasets · the metric canon), 33 raw → 30 unique candidates, top 8
verified against **primary evidence** — LICENSE files in the sdist/repo, PyPI
classifiers, dependency trees walked for GPL contamination, integration surfaces read in
source. NFR7 (no GPL family, incl. LGPL/AGPL) enforced throughout.

**Verified and recommended:**

| Repo | Licence (verified) | Role here |
|---|---|---|
| **JerBouma/FinanceToolkit** (5.2k★, release 2026-07-14) | MIT, dep tree clean | **The ratio canon.** 87 ratio functions counted in source across efficiency/liquidity/profitability/solvency/valuation, plus Piotroski F, Altman Z, Beneish M, DuPont, WACC. Every function is **pure pandas, zero I/O** — runnable directly on OUR as-filed facts, so PIT survives. Desk-side guarded import (its dep tree exceeds the runtime budget); also a cross-check oracle for `scoring.evaluate`. Its native FMP/yfinance fetch path is vendor-tier and unused. |
| **dgunning/edgartools** (already adopted; v5.45.1 released today) | MIT | **Segments.** Verified in source: `XBRL` parsing retains dimensioned facts (`dim_*` per fact, `query(include_dimensions=…)`), so per-segment revenue/operating income with filed dates is extractable from filings we already fetch. The HEYDUDE-vs-core question becomes desk-checkable arithmetic. |
| **SEC DERA Financial Statement Data Sets** + HansjoergW/**secfsdstools** (Apache-2.0) | public domain / Apache-2.0 | **Tier-1 replacement candidate.** The SEC's own quarterly zips: every as-filed statement fact with `adsh` and `filed`, keyless, free. Fixes the 19-tag ceiling at the source instead of per-name tier-2 fetches. secfsdstools' standardizers are plain-pandas and don't require its downloader. |
| **SEC frames API** | US Gov | Cross-sectional per-tag queries (one fact per filer per quarter) — cheap universe-wide coverage checks; same fair-use rules as companyfacts. |
| theOGognf/**finagg** (Apache-2.0, v2.0.0) | Apache-2.0 | Lighter alternative ratio layer (`compute_financial_ratios` is DataFrame-in/out). Dominated by FinanceToolkit; keep as reference. |
| john-friedman/**datamule** (MIT) | MIT | Scoped value: its 90KB us-gaap synonym mapping + FCF/EBITDA formula tables, and a 20KB inline-XBRL parser. Reference material more than a dependency. |
| **Arelle** (Apache-2.0, release 6 days old) | Apache-2.0 | Spec-complete XBRL processor; computes zero metrics itself. Heavy. Only if edgartools' XBRL layer ever falls short. |

**Excluded, with reasons on record** (the ones that matter): OpenBB — AGPL-3.0, banned
by NFR7, twice over; openesef — GPL-3.0; SimFin — *standardized* (silently restated)
data can never fire a monitor trigger; Sharadar/FMP/Tiingo/Finnhub — key-gated vendor
paths that duplicate either EDGAR (free, as-filed) or yfinance (tier 3);
FundamentalAnalysis — deprecated by its own author in favour of FinanceToolkit;
sec-parser, brel, python-xbrl, fibooks — unmaintained or archived.

## 4. Registry v2 (PROPOSED — awaits the owner's ratification)

Rules carried over unchanged: **no price-derived metric ever** (FR4/FR7); a metric
enters the registry only with measured coverage; `record` keeps refusing triggers on
uncomputable metrics; vendor values stay display-only. Feasibility column states what
each metric needs — "now" means computable from the 19 tier-1 tags today.

**The engine (cash):**

| # | Metric | Definition | Needs |
|---|---|---|---|
| 1 | owner_fcf_margin_pct | *(keep)* | now |
| 2 | owner_fcf_usd | *(keep)* | now |
| 3 | owner_fcf_per_share_usd | owner FCF ÷ diluted shares — the owner's compounding unit | now |
| 4 | fcf_conversion_pct | owner FCF ÷ net income — cash twin of accruals | now |
| 5 | cash_conversion_pct | OCF ÷ EBITDA | tier 2 (D&A) |

**Growth & reinvestment:**

| 6 | revenue_growth_pct | *(keep)* | now |
| 7 | owner_fcf_per_share_growth_pct | 3–5y CAGR, buyback-adjusted compounding | now |
| 8 | roic_pct | *(keep)* | now |
| 9 | incremental_roic_pct | ΔNOPAT ÷ Δinvested capital, 3y — the reinvestment-runway metric | now (caution: noisy) |
| 10 | capex_intensity_pct | capex ÷ revenue | now |
| 11 | rd_intensity_pct | R&D ÷ revenue — the owner's tech circle | tier 2 |

**Pricing power:**

| 12 | gross_margin_pct | *(keep)* | now |
| 13 | operating_margin_pct | OperatingIncomeLoss ÷ revenue — 1,834/1,904 tier-1 coverage | now |
| 14 | margin_stability_mad | 5y MAD of operating margin (the inversion layer's own arithmetic, exposed) | now |

**Balance sheet:**

| 15 | net_debt_to_ebitda | *(keep)* | tier 2 |
| 16 | interest_coverage_x | EBIT ÷ interest expense (already computed inside scoring's WACC path) | tier 2 |
| 17 | current_ratio | AssetsCurrent ÷ LiabilitiesCurrent | tier 2 |
| 18 | goodwill_pct_assets | goodwill + intangibles ÷ assets — acquired-vs-organic flag | tier 2 |

**Stewardship & integrity:**

| 19 | sbc_pct_of_revenue | *(keep)* | now |
| 20 | share_count_trend_pct_per_year | *(keep)* | now |
| 21 | accrual_divergence_pct | *(keep)* | now |
| 22 | shareholder_yield_split | dividends ÷ mcap and net buyback ÷ mcap, separately | tier 2 |
| 23 | tax_gap_pct | effective minus cash tax rate — an earnings-quality tell | tier 2 |
| 24 | acquisition_spend_pct_ocf | cash spent on acquisitions ÷ OCF — the HEYDUDE habit, watched | tier 2 |

**Composites (owner decides whether these are registry or display):** Piotroski F,
Altman Z, Beneish M — all tier 2, formulas cribbed from FinanceToolkit's source. They
are *level* scores; the standing rule that the two judgements never merge argues for
keeping them display-side unless the owner wants F-score deterioration as a trigger.

**Segments (deliberately NOT registry):** per-segment revenue share and growth are
extractable desk-side (edgartools, dimensioned facts) but not weekly-mechanical through
tier 2 — companyfacts drops dimensions. Segment triggers therefore stay event/narrative
questions, and the desk gains a filed-numbers segment sheet to answer them with.

## 5. Adoption plan (in order, each independently shippable)

1. **Expose what is already computed** (metrics 3, 4, 7, 9, 10, 13, 14, 16 partly):
   wiring + tests, zero new data, zero new dependencies.
2. **Widen tier 1**: regenerate the export with the full tag set (the raw JSONs already
   exist in `bt_cache/facts/`), or adopt SEC DERA FSDS as the export format. Kills most
   "tier 2 required" rows above at the source.
3. **FinanceToolkit, desk-side guarded** (like edgartools): the thesis packet gains a
   full ratio sheet; its pure functions double as a cross-check oracle for our own
   arithmetic in tests.
4. **Segment sheet** via edgartools dimensioned facts, feeding thesis research and
   monitor verdicts — never firing a rule alone.
5. Registry v2 lands in `thesis.METRICS` + `monitor` only after the owner ratifies this
   document; every new metric ships with measured coverage in the work-order packet.
