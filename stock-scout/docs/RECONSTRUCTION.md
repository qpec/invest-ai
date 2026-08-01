# Stock Scout — reconstruction specification

**Provenance.** The original `stock-scout` working tree (built 2026-07-29/30 by the owner's
personal agent on its own box) was lost. This directory is a faithful reconstruction from the
complete Telegram interaction history between the owner and the agent (64 messages,
2026-07-29 13:17 → 2026-07-30 21:55), plus the two assets the history says were vendored
from this repo: `agentcy/scout_grade.py` (751-line V/Q/G/D/M grader) and `agentcy/fetch/yf.py`
(hardened yfinance layer). Where the history pins an exact rule, threshold, or formula, this
spec pins it too and cites the message. Where the history is silent, the reconstruction uses
the repo's owner-ratified Scout v2 design (`docs/plans/2026-07-10-scout-v2-graded-screening-design.md`)
and the cited upstream (`virattt/ai-hedge-fund`) as ground truth, and says so.

**What the module is.** Iteration 2 of the system: value-first, no daemon/systemd/eToro.
A standalone pipeline: universe → paced fundamentals cache → grading (v2.3) → report +
audit datasheet → v3 owner-mode formation; plus an EDGAR point-in-time backtest layer that
shares the live decision code. Runs from this directory with only `yfinance pandas scipy`.

---

## 1. Version history evidenced by the chat (what must exist)

| Version | Chat msgs | Features |
|---|---|---|
| v1 | 2–10 | Universe 589 US+NL IT/HC mid-cap+; paced resumable populate; detached 15-min Telegram reporter; grader decoupled from agentcy runtime over a JSON cache; first A–F run (298 graded, 130 vetoed); report md + grades json |
| v2.1 | 16–19 | Own EV (mcap+debt−cash) replacing Yahoo EV + `EV_GAP` flag (>15%); share-class-mismatch flag (NCI>10% **and** EV gap>15% → share-trend leg neutral 50, dilution penalty off); float flag (deferred revenue >30% of revenue → "ROIC float-driven"); low-base floor (per-share-OFCF-CAGR leg dropped when base-year owner-FCF < 2% of that year's revenue) |
| v2.2 | 20–28 | Quarterly augment → TTM metrics (yield, margins, ROIC, self-funding, accruals; growth CAGRs stay annual; cash-destruction veto on TTM chain); cash-flow-quality veto (credit-loss provisions / write-off add-backs ≥ ~25% of OCF — catches lenders like DAVE **and** non-lenders like IPGP/AMRX); hard dilution veto >20%/yr (5–20%/yr keeps the −15 penalty); accruals on NI **including** NCI; ROIC capped at 1000% + flag when capital base ≤ 0 |
| v2.3 | 29–34 | From ai-hedge-fund: shadow margin-of-safety column (multi-stage DCF, never scored); proposal portfolio (top-15 conviction-weighted + risk clamps, clamped exposure → cash, audit trail); 13-point Buffett checklist per top-10 in the datasheet |
| Stage-2 | 37–39 | `data/stage2-YYYY-MM-DD.json` qualitative layer; datasheet auto-picks the file matching the run date and renders per-name analysis + recommendation + sources |
| Backtest | 42–44 | `bt_fetch.py` (EDGAR companyfacts + weekly prices, keyless), `pit.py` (point-in-time adapter: filed-date discipline, tag fallback chains, ±365d prior-YTD matching, multi-class shares fallback → neutral M leg), `scoring.py` (decision layer extracted; live + backtest share it bit-identically), `backtest.py` (quarterly grid from benchmark bars, 10 bp costs, delist handling, band cohorts A/B/C/D/F/VETOED) |
| v3 | 45–58 | Owner-mode: buy and sell are different decisions. Quality engine `B = 0.40·Q + 0.25·G + 0.20·D + 0.15·M`; price is an entry **gate** (V ≥ 20th percentile), not a score; 2 consecutive quarters of evidence before entry; exit only on veto / quality rank > 40 / extreme overvaluation; `backtest3.py` walk-forward harness (calibrate one half, blind-test the other, 18-option grid, `--top-n`); `formation.py` frozen rules + `formation-state.json` (squad, bench, transfers, since-quarter); persistence counter increments only when a real quarter has passed (msg 62) |
| Broad universe | 61–64 | `--broad`: all sectors from Small Cap up, US+NL, **excluding Financials and Real Estate** (cash-flow metrics misleading for banks/REITs) → ~2,700 names; `--fresh` re-populate sets the old cache aside as `cache-YYYY-MM-DD` |

Numbers in chat reports (589 names, 443 cached, 428 graded, +11.5%/yr, band table, etc.) are
**data outcomes of runs on 2026-07-29/30**, not code constants. Re-runs produce today's data.

---

## 2. Files

```
stock-scout/
  README.md            usage + provenance
  requirements.txt     yfinance, pandas, scipy
  universe.py          FinanceDatabase → universe.csv (default & --broad)
  populate.py          paced resumable yfinance cache → cache/<T>.json + progress.json
  augment.py           quarterly-statement augment of an existing cache (v2.2)
  reporter.py          detached 15-min Telegram progress reporter (msg 5-6 "hard geregeld")
  tg.py                stdlib Telegram client: send_message / send_document
  scoring.py           THE decision layer (pure; shared live + backtest, msg 44)
  grade.py             cache → scoring → reports/scout-run-<date>.md + scout-grades-<date>.json
                       + formation update (v3 is the live mode, msg 57-58)
  formation.py         frozen v3 owner-mode rules + formation-state.json
  datasheet.py         reports/datasheet-<date>.html audit datasheet (+ Stage-2 layer)
  bt_fetch.py          EDGAR companyfacts + weekly prices → bt_cache/
  pit.py               point-in-time fundamentals adapter over EDGAR facts
  backtest.py          v2-composite PIT backtest, band cohorts
  backtest3.py         v3 owner-mode + walk-forward harness (--top-n, rank cohorts)
  vendor/
    scout_grade.py     verbatim reference copy of agentcy/scout_grade.py (not imported)
    yf_fetch.py        hardened yfinance layer (adapted from agentcy/fetch/yf.py; imported)
  data/
    stage2-2026-07-30.json   Stage-2 qualitative layer reconstructed verbatim-in-substance
                             from msg 39 (ten verdicts + sources)
  docs/RECONSTRUCTION.md     this file
  reports/             generated output (kept, examples committed when produced)
  cache/, bt_cache/    gitignored data caches
```

All scripts are `python <script>.py` CLIs run from `stock-scout/`; shared imports are plain
module imports (`import scoring`), no package install.

---

## 3. Data contracts (pinned — every module conforms)

### 3.1 `universe.csv`
Columns: `symbol,name,sector,industry,country,market_cap,exchange,currency`.
`symbol` is the **yfinance** symbol (Euronext Amsterdam names carry `.AS`).

Build (msg 2/4): FinanceDatabase equities (keyless:
`https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/compression/equities.bz2`
— note `compression/`, NOT `database/`; verified reachable, ~15.5 MB — cached locally at
`data/equities.bz2`; `--equities-file` accepts a local copy). Default
filter: `country ∈ {United States, Netherlands}` · `sector ∈ {Information Technology,
Health Care}` · `market_cap ∈ {Mega Cap, Large Cap, Mid Cap}`. `--broad` (msg 64):
all sectors **except** `Financials`, `Real Estate`; adds `Small Cap`.
Cross-listing dedupe (msg 4, "the only_primary_listing pitfall solved properly"): drop
warrant/unit lines (an MLP's *common units* are kept), then group by normalized company
name and keep, in order of preference: (0) the home-market listing (NL company → `.AS`,
US company → bare US symbol), (1) a bare symbol on a major US venue, (2) any bare symbol,
(3) whatever is left — ties broken by shortest-then-alphabetical symbol. The tiering
matters: an earlier alphabetical fallback silently replaced primary listings with foreign
secondary lines (a São Paulo BDR instead of NXPI, a Berlin line instead of ARGX), so a
wrong-currency symbol got graded and the real name vanished.
Sanity anchors: the six Dutch names ADYEN.AS, ASML.AS, ASM.AS, BESI.AS, PHIA.AS, TWEKA.AS
survive the default filter, and ARGX/NXPI win their own groups (1AE.BE and N1XP34.SA do
not). Current real-database sizes: default 683 names (670 US, 13 NL), `--broad` 2,934.

**Known vendor-data limitation (not a code defect).** Grouping is only as good as
FinanceDatabase's `name` column, and that column is corrupt in both directions: ~16
unrelated US tickers all carry the name "Stem, Inc." and collapse into one group (CBU,
COLB, FIBK, LSTR, SBSAA, STEM and VSTM are dropped — VSTM/Verastem is a Health Care name
inside the owner's core circle), while some genuine cross-listings of one company carry
different sectors *and* industries (Boeing's `BCO` line is tagged "Professional Services").
That second fact is why the grouping key cannot simply be tightened to name+sector+industry
— it would split real cross-listings. Cost is ~7 names in 2,934 (0.2%); fixing it properly
needs an identity column the vendor does not reliably supply.

### 3.2 `cache/<SYMBOL>.json` (dots in symbols are kept; `/` → `-`)
```jsonc
{
  "ticker": "ADBE",
  "fetched_at": "2026-07-31T10:00:00+00:00",
  "meta": {"name": "...", "sector": "...", "industry": "...", "country": "..."},   // from universe row
  "currency": "USD",
  "price": {"close": 123.4, "date": "2026-07-30"},
  "price_basis": "raw",                                // share terms of that close (§3.6); always written
  "fast_info": { "last_price": ..., "market_cap": ..., "shares": ..., "currency": "USD", ... },  // plain floats/strings
  "shares": {"2025-07-01": 430000000.0, ...},          // get_shares_full, deduped last-per-date
  "splits": {"2025-01-15": 2.0, ...},                  // split events from the SAME bar call (ratio per effective date)
  "annual":    {"income": {"<period_end>": {"<row>": <float|null>, ...}}, "balance": {...}, "cashflow": {...}},
  "quarterly": { same shape, may be absent pre-augment }
}
```
Statement payloads keep **every row Yahoo returns** (the datasheet shows the exact matched
labels). Period ends are ISO dates. NaN → null.

`price_basis` (deviation 17): the share terms of `price.close`, in the §3.6 vocabulary —
`"raw"` (as traded that day; Yahoo's bars, and what every entry written before the key
holds) or `"split_adjusted_today"` (restated into today's share terms; what the keyless
vendors serve). It is **declared by the fetcher, never sniffed**, and always written out.
For a live entry the two coincide — "adjusted to today" *is* today's as-traded price — so
a market cap off a `split_adjusted_today` close is exact here; the distinction only bites
on historical bars (§3.6). A fallback vendor with no split feed leaves `splits` empty, so
deviation 8's restatement is inert for that entry and populate reports how many.

`splits` (deviation 8): `get_shares_full` counts are point-in-time and split-**unadjusted**,
so the raw series reads a 2-for-1 as +100% dilution. The events ride the existing
`Ticker.history(actions=True)` call — populate widens that one call to `period="5y"` — so
there is **no** second Yahoo request. Only real events are stored (Yahoo writes 0.0 on
ordinary days). Entries written before this key existed stay valid: **absent → no
adjustment**.

`progress.json` (written by populate/augment, read by reporter):
`{"task": "populate", "total": N, "done": N, "failed": N, "started_at": iso, "finished": bool, "finished_at": iso|null}`
plus `failures.log` (one `symbol<TAB>reason` per line; 404/dead tickers land here, msg 6).

### 3.3 `reports/scout-grades-<date>.json`
```jsonc
{
  "run_date": "YYYY-MM-DD", "version": "v2.3+v3", "universe": N, "graded": N, "vetoed": N, "insufficient": N,
  "names": [ {
    "symbol": "...", "name": "...", "sector": "...", "industry": "...", "tier": "Core|Adjacent|Outside",
    "grade": "A|B|C|D|F|VETOED|INSUFFICIENT", "composite": 81.7, "quality_score": 74.2,   // v3 engine B
    "pillars": {"v": ..., "q": ..., "g": ..., "d": ..., "m": ...},                        // null when suppressed
    "legs": { "<leg_id>": {"raw": ..., "percentile": ..., "cohort_n": ..., "score": ..., "note": "..."} },
    "veto": {"vetoed": false, "reason": "", "penalty": 0},
    "flags": [{"code": "EV_GAP|SHARE_CLASS|FLOAT_ROIC|LOW_BASE|ROIC_CAPPED|REINVESTOR", "message": "..."}],
    "ev": {"own": ..., "yahoo": ..., "gap_pct": ..., "yahoo_source": "field|derived|null"},
    "ttm": {"quarters": 4, "through": "YYYY-MM-DD", "basis": "quarterly|annual"},
    "mos": {"intrinsic_value": ..., "market_cap": ..., "mos_pct": ..., "wacc": ..., "growth": ..., "base_fcf": ...} | null,
    "buffett": {"score": 6, "max": 13, "items": [{"name": "...", "points": 2, "max": 2, "pass": true, "detail": "..."}]} | null,
    "scorecard": {                                    // the Owner's Scorecard, docs/SCORECARD-DESIGN.md
      "score": 78.5, "available_max": 97, "pct": 81,  // score/available_max; pct = whole % OF THE AVAILABLE max
      "band": "Exceptional|Strong|Mixed|Weak|Pass|VETOED|NO PRICE", "band_meaning": "...",
      "blocks": {"quality": {"points": 29.0, "max": 35, "metrics": ["roic", ...]}, "price": {...}, "safety": {...}, "stewardship": {...}},
      "metrics": {"<anchor_id>": {"value": ..., "points": 9.6, "max": 12, "pct": 80, "detail": "..."}},   // points/pct null = not computable
      "why": {"strongest": {"metric": ..., "label": ..., "value": ..., "points": ..., "max": ..., "pct": ..., "sentence": "..."}, "weakest": {...} },
      "consensus": {"green": 3, "of": 3, "lenses": {"scorecard": true, "margin_of_safety": true, "buffett": true}, "label": "...", "evidence": {"<lens>": "..."}},
      "coverage": {"available_max": 97, "full_max": 100, "scored": [...], "missing": [{"metric": ..., "label": ..., "block": ..., "points": 3, "reason": "..."}], "missing_points": 3},
      "veto": {"vetoed": false, "reason": "", "penalty": 0},
      "notes": ["..."]
    } | null                                          // null for VETOED/INSUFFICIENT names
  } ],
  "portfolio": {"positions": [{"symbol": ..., "weight": ..., "conviction": ...}], "cash": ..., "clamps": [...]},
  "formation": { ...contents of formation-state.json after this run... }
}
```
`legs` ids: `v_yield`, `q_roic`, `q_gm`, `q_ofcf_margin`, `g_revenue`, `g_ps_ofcf`,
`d_net_debt`, `d_self_funding`, `d_sbc`, `m_shares`, `m_accruals`.

Units are NOT uniform and must be passed explicitly to any formatter: `ev.gap_pct` is in
**percent**, while `mos.mos_pct`, `mos.growth` and `mos.wacc` are **fractions**. (Inferring
the unit from magnitude renders a sub-1.5% EV gap 100× too large and a margin of safety
above +150% 100× too small.) `ev.yahoo_source` is `"field"` when a Yahoo enterprise value
was supplied and `"derived"` when the listed-class reference EV was reconstructed (§6.13).

`scorecard` is written by `grade.py` for **every graded name** (A–F) as
`scorecard.scorecard(bundle, scored_row=row)` — the card is built from the row that was
just scored, so the absolute card and the percentile legs read one computation and cannot
disagree. It is `null` for VETOED and INSUFFICIENT names, exactly like `mos`/`buffett`.
Its `metrics` keys are the ids of `scorecard.ANCHORS` (`roic`, `gross_margin`,
`gross_margin_cv`, `owner_fcf_margin`, `revenue_growth`, `owner_fcf_yield`,
`margin_of_safety`, `net_debt_ebitda`, `self_funding`, `sbc`, `current_ratio`,
`share_count_trend`, `accruals`, `capital_returned`), and the anchor table itself (label,
floor, target, points, unit, provenance) is **not** duplicated into the JSON — consumers
read it from `scorecard.ANCHORS`, which is the source of truth for the design's §3
provenance table.

Three units-and-honesty rules bind every consumer of this field, and they are the reason
the block/coverage detail is stored rather than recomputed downstream: `pct` is a
percentage of `available_max`, **not** of 100 (a name scoring 48 of an available 75
reports `48/75 (64%)`, never `48/100`); a `points`/`pct` of `null` means "not computable",
which shrinks `available_max` and is named in `coverage.missing` — never a silent zero;
and the two special bands carry no verdict at all — `VETOED` has `score`/`pct` `null` and
must never be ranked, `NO PRICE` is a quality profile that must never be rendered as an
x/100 verdict (design §4.1, the single most important rule in that document).

### 3.4 `formation-state.json` (v3, msgs 57-58, 62)
```jsonc
{
  "as_of": "YYYY-MM-DD", "quarter": "2026Q3",         // persistence increments only on quarter change (msg 62)
  "slots": 15,
  "squad": [{"symbol": "...", "since": "2026Q2", "entered_date": "YYYY-MM-DD", "quality_rank": 7, "streak": 3}],
  "bench": [{"symbol": "...", "streak": 1, "needed": 2}],
  "transfers": [{"date": "YYYY-MM-DD", "action": "in|out", "symbol": "...", "reason": "..."}]   // full history, append-only
}
```

### 3.5 `data/stage2-<date>.json`
```jsonc
{ "run_date": "YYYY-MM-DD",
  "analyses": { "<SYMBOL>": { "verdict": "Sterke kandidaat|Kandidaat|Kandidaat met voorbehoud|Terughoudend",
      "analysis": "...", "sources": [{"title": "...", "url": "..."}] } } }
```
The datasheet uses the file whose date == run date, else the newest file ≤ run date.

### 3.6 `bt_cache/`
`company_tickers.json` (SEC symbol→CIK), `facts/<SYMBOL>.json` (raw companyfacts **plus a
`"symbol"` annotation**), `prices/<SYMBOL>.json`, `prices/SPY.json`.
All EDGAR calls carry a real `User-Agent` and are paced ≤ 8 req/s.

Filenames sanitize `/` → `-` (BRK/B → `BRK-B.json`), so the TRUE symbol must travel inside
the file — keying by filename stem loses it, and the name then misses its universe meta
row (no sector → wrong tier and wrong sector cohort). The price file:

```jsonc
{ "symbol": "BRK/B",
  "bars":   {"YYYY-MM-DD": {"close": <raw>, "adj_close": <adjusted>}, ...},
  "splits": {"YYYY-MM-DD": <ratio>, ...},       // e.g. 2.0 on a 2-for-1 effective date
  "price_basis": "raw" | "split_adjusted_today" }   // share terms of every close in `bars`
```

Both prices are stored because they do different jobs: **anything multiplied by a share
count (market cap, own EV, WACC, MoS) must use the raw close**, since adjusted closes are
retroactively rescaled by every later split and dividend and would import the future into
every historical tick; total-return math (NAV, forward returns, the benchmark track) uses
`adj_close`. Legacy grids of plain floats still load, with the single value standing for
both fields — degraded, detectable, and disclosed in the report. Splits ride the same
`actions=True` fetch (no extra Yahoo call) and let the backtest tell a 2:1 split from
100%/yr dilution; `--keep-legacy-prices` opts out of refetching old grids.

`price_basis` (deviation 17) closes the second, invisible ambiguity: "raw close" pins down
dividends but **not splits**, and vendors disagree. `"raw"` means the price as it traded on
the bar's own day (Yahoo's Close, and the meaning of every file written before the key).
`"split_adjusted_today"` means that same price divided by every split since (what the
keyless vendors serve: NVDA's 2024-05-28 bar reads ≈109.6 there, ≈1096 is what traded).
The writer **declares** it; a reader never infers it, because nothing in a price series
reveals it and reading a today-basis close as raw understates a historical market cap by
the whole split factor. `pit.as_of_bundle` takes the declaration (one basis, or a
`{symbol: basis}` map for a cache written by several sources) and puts **both sides** of
`shares × price` into the same terms — for a today-basis close the as-reported dei count is
restated into today's share terms via `scoring.adjusted_shares_series`, after which the
future-split factor cancels exactly and the product is the true historical market cap in
dollars. Grids from different sources may therefore sit side by side; each file answers for
itself. Without split history the restatement cannot run: the bundle carries
`market_cap_split_unadjusted` and the fetcher counts those grids at the end of the run.

---

## 4. scoring.py — the shared decision layer (pure functions, no I/O)

The heart. `grade.py` (live, from the yfinance cache) and `backtest*.py` (PIT, from EDGAR)
both feed it the same `Bundle` and must get bit-identical scores (msg 44: "regressie-getest
bit-identiek"). Nothing in this module reads files, the network, or the clock.

### 4.1 Input: `Bundle`
A per-name dict assembled by the callers:
```jsonc
{
  "symbol", "sector", "industry", "name",
  "market_cap": float|null, "yahoo_ev": float|null, "price": float|null,
  "shares_series": [["YYYY-MM-DD", float], ...],       // ascending, deduped, split-UNadjusted
  "splits": {"YYYY-MM-DD": ratio, ...},                // optional; absent -> {} -> no adjustment
  "annual":    {"income": {pe: {row: val}}, "balance": ..., "cashflow": ...},
  "quarterly": {... or {} ...}
}
```
Row labels are Yahoo's; the PIT adapter maps EDGAR tags **to the same labels** (that is the
decoupling seam). Row-label fallback chains used by extraction (first present wins):
- Revenue `Total Revenue`→`Operating Revenue`; EBITDA `EBITDA`→`Normalized EBITDA`;
  EBIT `EBIT`→`Operating Income`; NI `Net Income`; NI incl NCI
  `Net Income Including Noncontrolling Interests`→`Net Income Continuous Operations`→`Net Income`;
  Gross Profit `Gross Profit`; Operating Income `Operating Income`→`EBIT`.
- Balance: `Total Debt`; `Cash And Cash Equivalents`→`Cash Cash Equivalents And Short Term Investments`;
  `Working Capital`; `Total Assets`; `Current Assets`; `Current Liabilities`;
  equity `Stockholders Equity`→`Common Stock Equity`; NCI `Minority Interest`;
  deferred revenue `Current Deferred Revenue`(+`Non Current Deferred Revenue` if present)→`Deferred Revenue`.
- Cashflow: `Operating Cash Flow`; `Capital Expenditure`; `Stock Based Compensation`;
  `Depreciation And Amortization`→`Depreciation Amortization Depletion`; credit-loss add-backs:
  any of `Provision For Doubtful Accounts`, `Provisionand Write Offof Assets`,
  `Change In Loss Reserves`, `Provision For Loan Lease And Other Losses`,
  `Allowance For Funds Used During Construction` — summed when present.

### 4.2 TTM assembly (v2.2)
- The TTM window is **one aligned period set**: the newest 4 period_ends present in **both**
  the quarterly income and the quarterly cashflow statement (their intersection), each
  carrying the needed rows. Every flow is summed over exactly those periods; balance-sheet
  items stay latest-period. Income and cashflow must describe the same 12 months or accrual
  divergence, owner-FCF/revenue and SBC/revenue mix windows (deviation 9). The chosen
  periods are returned as `ttm["periods"]` (ascending).
- Fewer than 4 **common** periods → fall back to the newest **annual** period as the TTM
  proxy; basis "annual" (that is the msg 26 "dekking 413/429" split).
- Growth CAGRs always use the **annual** series (msg 23: "groei-CAGR's blijven bewust op jaarbasis").
- Per-period normalized owner-FCF (Stage-1.5 rule, vendored grader lines 34-76):
  `OCF − min(|CapEx|, D&A) − SBC`; D&A absent → maintenance proxy = |CapEx|.
- Cash-destruction test (v2.2, msg 23): negative in **every** annual period **and** TTM ≤ 0
  → veto; a recovered burner (TTM > 0) escapes; a still-burner stays vetoed.

### 4.3 Metrics per pillar (raw values; scored via sector percentiles)
Identical to the vendored grader (design §1, Stage-1.5) with the v2.x amendments:
- **V**: owner-FCF yield = TTM normalized owner-FCF / **own EV**, own EV = market_cap +
  Total Debt − Cash (v2.1, msg 19 item 1). P/owner-FCF as display companion.
- **Q**: ROIC = TTM EBIT / Greenblatt denominator (Working Capital + (Total Assets −
  Current Assets − Cash)), capped at 1000% with flag `ROIC_CAPPED` when denominator ≤ 0
  **and TTM EBIT > 0** (v2.2 bonus catch, msg 23 item 5 — the capital-light/float-financed
  Adobe case); denominator ≤ 0 with EBIT ≤ 0 is not a 1000% return: the leg is **None**
  (integrity-suspend, no floor factor, no carve-out — deviation 10); gross-margin
  level×stability one leg (level percentile × stability percentile/100); owner-FCF margin TTM.
- **G**: annual revenue CAGR + annual per-share owner-FCF CAGR, each ROIC-floor-gated
  (× min(1, ROIC/15%)); per-share leg dropped + flag `LOW_BASE` when base-year owner-FCF
  < 2% of that year's revenue (v2.1 item 4); both legs None → G = 50 neutral.
- **D**: net debt/EBITDA (TTM EBITDA); owner-FCF positive (TTM) → 100/0 leg; SBC/revenue TTM.
- **M**: share-count trend %/yr on the **split-adjusted** series — every observation restated
  in today's share terms by the cumulative split ratio applied after its date, so a 2-for-1
  reads ~0%/yr instead of +100%/yr (deviation 8; the same adjusted series feeds the per-share
  owner-FCF CAGR in **G**). Lower better; leg **neutral 50** and dilution penalty off when
  flag `SHARE_CLASS` set — v2.1 item 2; accrual divergence = (NI **incl. NCI** TTM − OCF TTM)/
  revenue TTM (v2.2 item 4), lower better.

### 4.4 Veto / penalty order (all evaluated on the bundle before scoring)
The veto layer runs **before** the §4.6 integrity-suspend: a veto is a fact about the bundle,
not a score, so a name whose EBITDA is 0 while it carries net debt is VETOED on the leverage
rule rather than suspended for the ratio that same 0 makes uncomputable (deviation 12). Only
names that survive the veto layer are then checked for missing required metrics.
1. **Leverage veto** (design §2): net debt/EBITDA > 4 (TTM), or EBITDA ≤ 0 with net debt > 0
   (EBITDA exactly 0 included).
2. **Cash-flow-quality veto** (v2.2, msg 26/28): credit-loss/write-off add-backs ≥ 25% of
   positive TTM OCF → `VETOED "cash-flow quality: OCF leans …%"` (DAVE 28%, IPGP 77%, AMRX 28%
   all fire; threshold pinned at 0.25).
3. **Dilution veto** (v2.2): share-count CAGR > 20%/yr → VETOED (QXO 909%/yr, VSAT, GBTG);
   **suppressed when `SHARE_CLASS` is set** (deviation 11) — §4.5 already declares that
   trend untrustworthy for those names, and a trend that cannot score a leg cannot veto.
4. **Cash-destruction veto** per §4.2; reinvestor carve-out unchanged from the vendored
   grader (ROIC > 15% and revenue growth > 10%/yr → flagged `REINVESTOR`, not vetoed; an
   unusable ROIC (None, §4.3) never qualifies).
5. **Dilution penalty**: 5%/yr < CAGR ≤ 20%/yr → −15, flagged (suppressed when `SHARE_CLASS`).

### 4.5 Flags (v2.1, msg 19 — computed for every name, shown everywhere)
- `EV_GAP`: |own EV − reference EV| / own EV > 15%. The reference EV is the supplied
  `yahoo_ev` when present (`ev.yahoo_source = "field"`); otherwise it is **derived** from the
  cache as `price × latest listed shares + Total Debt − Cash` (`"derived"`, deviation 13),
  because yfinance's FastInfo carries no enterprise value and the `info`/quoteSummary path
  is banned and blocked — `yahoo_ev` is None in every live run, which left this flag and
  `SHARE_CLASS` structurally dead. The Up-C signal *is* a share-count mismatch: the quoted
  market cap counts all units, `get_shares_full` reports the registrant's listed class. A
  single-class company has implied units ≈ reported shares → gap ≈ 0 → no flag; an Up-C
  shows a positive gap. No reference at all (no price/shares) → no gap, no flag.
- `SHARE_CLASS`: NCI / total equity > 10% **and** EV gap > 15% (both conditions — Tenet's
  41% NCI with a 10% gap must NOT flag, msg 19). Sets the M share-trend leg to neutral 50
  and switches **both** the dilution penalty and the hard dilution veto off (§4.4).
- `FLOAT_ROIC`: deferred revenue > 30% of TTM revenue → "ROIC float-driven".
- `LOW_BASE`, `ROIC_CAPPED`, `REINVESTOR` as above.

### 4.6 Scoring pass
Sector percentile machinery, pillar aggregation, composite weights
`0.25/0.25/0.20/0.15/0.15`, grade bands ≥80 A / ≥65 B / ≥50 C / ≥35 D / F, tiering
(Core/Adjacent/Outside) — all **identical to the vendored grader**. Integrity-suspend
(INSUFFICIENT with reason) whenever a required metric is None **and no §4.4 veto fired
first**; None never reaches `percentileofscore`. Vetoed names are suppressed, never ranked.

### 4.7 v3 quality engine + gates (msgs 50, 58 — frozen)
- `quality_score = 0.40·Q + 0.25·G + 0.20·D + 0.15·M` (no V).
- Price gate: V-percentile ≥ 20 (V pillar score, which is already the sector percentile of
  owner-FCF yield).
- Persistence: 2 consecutive **quarters** in the entry pool before buying.
- Exit only on: veto fires · quality rank > 40 · extreme overvaluation (V-percentile < 5).
- Constants exported: `W_QUALITY = {"q":.40,"g":.25,"d":.20,"m":.15}`, `GATE_V_PCTL = 20.0`,
  `PERSISTENCE_QUARTERS = 2`, `EXIT_RANK = 40`, `EXIT_V_PCTL = 5.0`, `SLOTS = 15`.

### 4.8 v2.3 adoptions (shadow layers — never enter the composite)
- **Margin of safety** (msg 34 item 1, formulas per ai-hedge-fund `calculate_enhanced_dcf_value`
  + `calculate_wacc`): base FCF = max(TTM owner-FCF, 0.85 × 3-yr average annual owner-FCF);
  growth = annual revenue CAGR capped at 25% (10% when market cap > $200B); 3-stage
  projection (years 1-3 at g; years 4-7 declining transition; terminal min(3%, 0.6·g));
  WACC = CAPM blend clamped to [6%, 20%]; FCF-volatility quality factor
  max(0.7, 1 − 0.5·CV). `mos_pct = (intrinsic − market_cap)/market_cap`. Null when base
  FCF ≤ 0.
- **Buffett checklist** (msg 34 item 3; 13 points): fundamentals 7 (ROE>15% +2, D/E<0.5 +2,
  operating margin>15% +2, current ratio>1.5 +1), consistency 3 (annual NI non-decreasing
  across available periods +3), moat 3 (ROE>15% in ≥80% of annual periods +2 / ≥60% +1;
  avg operating margin>20% and recent ≥ older +1). Annual series, newest first.
- **Proposal portfolio** (msg 34 item 2; ai-hedge-fund `construction.py`+`limits.py`):
  candidates = top-15 by composite; conviction = composite; abstention ≠ neutral (a name
  without a composite never becomes a 0-vote); weights = conviction/Σconviction × gross
  target 1.0; clamps: max position 10%, max gross 100%; clamped exposure **stays cash**
  ("conviction requests, risk disposes"); every clamp logged.

---

## 5. Pipeline scripts

### 5.1 `universe.py`
`python universe.py [--broad] [--out universe.csv] [--equities-file PATH]` — §3.1. Prints
universe size + NL names kept. Downloads to `data/equities.bz2` once, reuses thereafter.

### 5.2 `populate.py`
`python populate.py [--universe universe.csv] [--limit N] [--only SYM,SYM] [--fresh] [--annual-only] [--price-source {auto,yahoo,stockanalysis}]`
- Per symbol (default: annual **and** quarterly in one pass — msg 62 "nu mét kwartaaldata in
  één pass"; `--annual-only` reproduces the v1 behavior): fast_info, daily bars (close,
  currency **and split events** — one `history(actions=True)` call widened to `period="5y"`,
  §3.2 `splits`), shares_full, annual statements, quarterly statements → `cache/<SYM>.json`.
- Paced via `vendor/yf_fetch.py` primitives (flock + spacing + rate-limit ladder;
  spacing default 0.6 s ± jitter, `--pace` to override).
- Resumable: existing fresh cache entries are skipped (`--max-age-days`, default 3).
- Failures logged to `failures.log`, counted in `progress.json`, never fatal (msg 6: 404s on
  dead tickers are logged and skipped).
- `--fresh` (msg 62): move existing `cache/` to `cache-<YYYY-MM-DD>/` first.
- Writes `progress.json` after every symbol; marks `finished` at the end.
- `--price-source` (default `auto`, deviation 17) picks the vendor behind the §3.2 `price`
  block only — fast_info, shares and statements are always Yahoo's. `auto` runs Yahoo's
  daily bars first and steps down to `pricesrc`'s keyless source once Yahoo throttles (a
  rate limit retires the Yahoo price leg for the rest of the run instead of ending it);
  `yahoo` keeps the old behavior including stopping the run on a rate limit. Every entry
  records `price_basis` (§3.2).
- **The live path is where the alternative source is a full substitute, not a compromise.**
  A `split_adjusted_today` close is the as-traded price *divided by every split since*, and
  no split can lie after today, so for a run priced today the two bases are the same number
  and `shares × close` is exact to the cent. Only historical bars need the restatement of
  §3.6. What is lost is the split *feed*: the keyless vendor has none, so such entries carry
  no `splits`, deviation 8's restatement is inert for them, and a name that split recently
  reads as dilution until Yahoo is reachable again. populate says how many at the end.

### 5.3 `augment.py`
`python augment.py [--universe universe.csv]` — add `quarterly` to cache entries that lack
it (v2.2 path for an annual-only cache). Same pacing/progress/failure contracts.

### 5.4 `reporter.py` (msg 5-6: "Hard geregeld", three layers)
`python reporter.py [--interval 900] [--max-hours 4] [--progress progress.json]`
- Detached-friendly (nohup); every interval sends
  `⏳ Stock Scout <task>: <done>/<total> gecached (<pct>%) · <failed> dode tickers · <rate>/min · ETA ~<m> min`
  via `tg.py`; on `finished` sends `✅ Stock Scout <task> KLAAR: <done>/<total> gecached, <failed> dode tickers overgeslagen.`
  and exits; hard-exits after `--max-hours` (safety limit).
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` env; absent → prints to stdout instead (still
  usable in dev).

### 5.5 `grade.py`
`python grade.py [--universe universe.csv] [--cache cache] [--date YYYY-MM-DD] [--no-formation] [--telegram]`
1. Load universe + cache → bundles (skip uncached; count them).
2. `scoring.score_universe` → scored names (+flags, veto, legs, EV, TTM basis).
3. MoS + Buffett + the Owner's Scorecard for every graded name (cheap; datasheet shows top-10).
4. Portfolio proposal (§4.8).
5. Formation update via `formation.py` (v3 live mode, msg 58) unless `--no-formation`.
6. Write `reports/scout-run-<date>.md` + `reports/scout-grades-<date>.json`.
7. `--telegram`: send the md summary + attach the datasheet if present.
`--date` is validated as a real ISO `YYYY-MM-DD` at parse time (both discovery seams
regex-match the date, so a malformed one produced reports nothing could find). The veto
breakdown groups by **distinct sub-reason** (family rollup plus one line per sub-reason
when a family has more than one), preserving the msg-10 split between "net debt/EBITDA > 4"
and "EBITDA ≤ 0 with net debt". The header reports uncached AND unreadable cache entries
separately, with a named block listing each unreadable symbol and its reason — one corrupt
file must never abort a run.

Report md sections (msgs 10, 28, 32, 57; re-ordered for the Owner's Scorecard, 2026-08-01
— nothing was deleted, the scorecard was put in front and the percentile view relabelled):

1. **Header** — counts (universe/graded/veto/insufficient/uncached/unreadable), band
   occupancy from the scorecard, then the grade counts explicitly labelled *"rang in
   sector (context)"*.
2. **"Hoe je dit leest"** — five lines rendered from `scorecard`'s own constants: the score
   is absolute; read bands, not ranks (`scorecard.NOISE_FLOOR`, ±5 points); what consensus
   n/3 counts and at which thresholds; that NO PRICE is a quality profile and not a verdict
   (§4.1) and that a veto suppresses rather than ranks (§4.3); and that grade+composite is
   context. It sits above the first `## ` heading, so `summary_head` carries it to Telegram.
3. **Veto breakdown** by distinct sub-reason, and the named unreadable-cache block.
4. **`## Scorecard — absolute punten`** — the main table, sorted by `pct` descending but
   printed as `### <band> <range> (n) — <meaning>` groups so the output cannot invite
   reading rank 9 against rank 11 (design §1.2). Columns, in this order: symbol · name ·
   score · band · consensus · Q · P · S · St · flags · *rang in sector (context)*. There is
   deliberately **no rank column**. The score cell reads `81/100`, or
   `81/100 · 78.5/97 pt` when a metric was not computable (§4.2). Empty bands are skipped;
   the header line already reports the occupancy of all of them.
5. **`## Zonder band (geen oordeel)`** — everything that carries no verdict, kept out of the
   ordering on purpose: `### NO PRICE` (its own table, points out of what was available,
   never x/100, with the §4.1 disclaimer printed verbatim), `### VETOED` (name + reason,
   capped at `grade.VETOED_LIST_MAX` with the tail counted) and any graded name whose card
   is missing.
6. **`## Sectorrelatieve context (rang binnen sector)`** — the unchanged tier-sectioned A-F
   tables (`### Core|Adjacent|Outside`; symbol, name, grade, composite, V/Q/G/D/M, MoS%,
   flags), now under a heading that says what they are: where a name stands among its
   sector peers, still the engine under De Formatie and the only walk-forward-validated
   ranking the system owns (SCORECARD-DESIGN §6).
7. **NL names call-out** — now scorecard-first per line, with the sector rank in brackets.
8. **De Formatie** (squad with since/streak/rank, transfers with reasons, bench with
   needed-quarters, open slots as cash) replacing the old top-15 ranking.
9. **Honest-evidence footer** (a grade is a research shortlist, not a buy list).

### 5.6 `formation.py`
Library + CLI (`python formation.py --show`). `update(state, scored, run_date) -> (state', transfers)`
implementing §4.7 against `formation-state.json`; quarter key = calendar quarter of
run_date; streaks/persistence advance **only** when the quarter differs from `state.quarter`
(msg 62); same-quarter re-runs refresh ranks/gates without advancing streaks. Bootstrap
(first run, msg 58 "PIT-bootstrap"): names already passing gate+rank enter immediately with
`since = current quarter`; the rest of the **candidate band** goes to the bench with
streak 1. The band, not the pool, is what makes a bench possible: the entry pool is capped
at rank ≤ SLOTS and the squad seats exactly that many, so "the rest of the pool" is empty
by construction. Bench = gate-passing names ranked ≤ `EXIT_RANK` that are not seated;
promotion requires persistence **and** rank ≤ SLOTS **and** an open slot. (This refines
§4.7's "2 consecutive quarters in the entry pool": evidence accrues in the band, entry
still demands the pool — which is what msg 58's 14-seated/5-benched first formation shows,
since a benched name with an open slot available must have been outside the top-15.) Slots
never exceed 15; a free slot with no proven candidate stays open ("liever cash dan een
kandidaat zonder bewijs").

### 5.7 `datasheet.py`
`python datasheet.py [--grades reports/scout-grades-<date>.json] [--top 10] [--out reports/datasheet-<date>.html]`
Self-contained HTML (inline CSS/JS, no external requests), theme-aware, ~top-10 cards
(selected, as before, by the percentile composite — the datasheet audits the run the
formation was built from):
- Header: run date, version, counts, band occupancy, grade chips labelled as sector-rank
  context, veto breakdown, formation one-liner, and one collapsible **anchor-provenance
  table** rendered from `scorecard.ANCHORS` (metric, block, floor, target, points, where
  the line comes from) — the design's §3 ledger, once per page rather than per card.
- Per card, the **Owner's Scorecard first** (design §5): headline `pct/100` + band + the
  band's plain-language meaning; the four block bars (points out of the block's *available*
  maximum, with the full maximum named when a metric dropped out); the "why" sentences
  (strongest and weakest metric, named with their values); the consensus badge with its
  per-lens evidence; a coverage line naming every metric that was not computable, worth how
  many points, and why (§4.2); the run notes; and a table of all 14 metrics — label, raw
  value **in its own unit**, the floor→target ramp it was scored on, and the points earned
  — rendered from `scorecard.ANCHORS`, never hardcoded, so a point can be audited exactly
  the way a percentile already could. A `VETOED` card shows no score and a `NO PRICE` card
  shows its points out of what was available with the §4.1 disclaimer — neither is ever
  rendered as an x/100 verdict.
- Then, unchanged, the whole pre-existing evidence chain (msg 13): Stage-2 analysis block
  when available (msg 39); score build-up table — every leg: raw value → sector percentile
  (with cohort size) → leg score; pillar × weight → composite (both now labelled as
  sector-relative context); the veto/penalty checks with their actual values; flags with
  explanations (msg 18); own-EV vs Yahoo-EV line; owner-FCF per period table; the exact
  statement rows used (which label matched, per period); fast_info snapshot; MoS block
  (inputs + intrinsic vs market cap); Buffett checklist items with pass/fail.
- Independent recompute, **twice** — a scorecard the reader cannot verify is no better than
  the number it replaces: the composite re-derived in the page's JS from the stored
  legs/weights/penalty (msg 13), and the scorecard re-derived from the embedded per-metric
  points (block sums, available maximum, total) plus each metric's own §2 ramp from its
  embedded value and anchors. Both render "✓ komt overeen" / "✗ afwijking" per card, and
  the scorecard check names what disagreed.
- "Alles uitklappen" button; first card pre-opened.

`datasheet.py` is stdlib-only except for `from scorecard import ANCHORS, …`. That import is
the anchor **table** — labels, floors, targets, points, units, provenance — not the
computation under audit: every number on the page still comes from the grades JSON, and the
re-derivation still happens in the page's own JS. A metric id the table does not know
degrades to its stored `detail` string, and a grades JSON without a `scorecard` key (an
older run) renders the rest of the card with a named note rather than failing the build.

### 5.8 `bt_fetch.py`
`python bt_fetch.py [--universe universe.csv] [--start 2020-01-01] [--limit N] [--price-source {auto,yahoo,stockanalysis}]`
SEC `company_tickers.json` → CIK map (cached); `companyfacts` per symbol → `bt_cache/facts/`;
weekly raw+adj close (`SPY` + universe) → `bt_cache/prices/`. Paced, resumable,
progress.json contract so `reporter.py` works for it too.

`--price-source` (default `auto`, deviation 17) selects the weekly price vendor; EDGAR is
untouched by it.
- `yahoo` is the unchanged raw+adjusted path: the vendored `fetch_weekly_bars` supplies
  `adj_close`, a supplementary paced `actions=True` call supplies the raw Close **and** the
  split events, the grid declares `price_basis: "raw"`, and a rate limit still stops the run.
- `stockanalysis` is `pricesrc`'s keyless source:
  `GET https://stockanalysis.com/api/symbol/s/<SYM>/history?range=<span>&period=Weekly`,
  no key, ~0.3 s/request, a browser `User-Agent` **required** (urllib's default is answered
  403). `c` → `close`, `a` → `adj_close`, and the grid declares
  `price_basis: "split_adjusted_today"`. **Range caveat:** only the spans the API honors may
  be used (`6M`, `YTD`, `5Y`, `10Y`) — `MAX`, `ALL`, `20Y` and the like are not errors there,
  they silently return 52 weekly bars, which would grade a ten-year backtest on one year of
  prices. `10Y` is the default and reaches 2016 (521 weekly bars for ADBE/NVDA, verified).
  The source has **no split feed**, so its grids carry no `splits`.
- `auto` runs the Yahoo path first and steps down to the keyless source when it refuses; a
  rate limit retires the Yahoo leg for the rest of the run rather than ending the run, which
  is the point on a 429'd box. Files from different sources coexist — each declares its own
  basis (§3.6) — and the run ends by reporting how many grids are today-basis and how many
  of those have no split history (those market caps come back
  `market_cap_split_unadjusted`).

### 5.9 `pit.py`
`as_of_bundle(facts, symbol, meta, as_of, prices) -> Bundle|None` — EDGAR→Bundle with
**filed-date discipline** (only facts `filed ≤ as_of`; the value used is the latest-filed
for its period). Tag chains (msg 44 adversarial fixes pinned):
- Revenue: `RevenueFromContractWithCustomerExcludingAssessedTax` → `Revenues` →
  `SalesRevenueNet` (ADBE reports `Revenues`).
- OCF `NetCashProvidedByUsedInOperatingActivities`; CapEx
  `PaymentsToAcquirePropertyPlantAndEquipment`; SBC `ShareBasedCompensation`;
  D&A `DepreciationDepletionAndAmortization` → `DepreciationAndAmortization`;
  NI `NetIncomeLoss`; NI-incl-NCI `ProfitLoss` → `NetIncomeLoss`;
  EBIT `OperatingIncomeLoss`; EBITDA = EBIT + D&A;
  Gross profit `GrossProfit` (absent → leg degrades);
  Debt `LongTermDebt` else `LongTermDebtNoncurrent`+`LongTermDebtCurrent`(+`ShortTermBorrowings`, missing → 0 **only when** one long-term piece exists, else None);
  Cash `CashAndCashEquivalentsAtCarryingValue`;
  Equity `StockholdersEquity`; NCI from `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` − `StockholdersEquity`;
  Current assets/liabilities `AssetsCurrent`/`LiabilitiesCurrent`; Total assets `Assets`;
  Working Capital = AssetsCurrent − LiabilitiesCurrent.
- Quarterly flow derivation: income/cashflow facts arrive as quarterly frames or YTD; a
  YTD value minus the prior YTD whose period-start matches within **±365 days** handles
  broken fiscal years (msg 44); durations ≤ 100 days pass through as true quarters.
- Shares: `dei:EntityCommonStockSharesOutstanding` summed across share classes per filed
  date; when class rows are inconsistent → shares series empty → the M share-trend leg is
  neutral (msg 44 "multi-class-shares-fallback met neutrale M-leg").
- market_cap = shares_at(as_of) × the **raw** close at as_of (never the adjusted one —
  §3.6); `adj_close` is for total return only.
- Multi-class rule: an inconsistent filing empties the share SERIES (so the M share-trend
  leg goes neutral) **and** still yields a fallback share count for the market cap, so the
  name grades instead of vanishing as INSUFFICIENT; `shares_basis`
  ("series" | "fallback-sum" | "fallback-largest") records which path was used.
- Quarter derivation subtracts a prior **cumulative** only — same period-start (±7 days for
  52/53-week wobble), or a genuine cumulative (span > 100 days) whose start matches within
  ±365 days for broken fiscal years. A discrete sibling quarter is never the subtrahend
  (9M-YTD minus a discrete Q2 would book Q1+Q3 as Q3).
- `splits` from the §3.6 grid, filtered to events **on or before as_of**, reach the bundle
  so as-reported dei counts are restated into as_of's share terms (§6.14).
- **Debt on a repaid balance sheet:** EDGAR stops carrying `LongTermDebt*` once a filer
  repays, so a properly tagged date (total assets AND cash present) with no debt tag reads
  as 0.0 — but the most recent earlier debt observation within 400 days is carried forward
  first, so the error always leans toward MORE leverage and a tagging gap can never sneak a
  levered name past the §4.4 veto (§6.15).
- **Gross profit:** the tagged `GrossProfit`, else revenue − cost of revenue
  (`CostOfRevenue` → `CostOfGoodsAndServicesSold` → `CostOfServices` → `CostOfGoodsSold` →
  `CostOfSales`). Filers need not present a gross-profit line, and the Q gross-margin leg is
  REQUIRED (§4.6), so without the derivation real names suspend (§6.16).

### 5.10 `backtest.py`
`python backtest.py [--start 2021-03-01] [--end today] [--top-n 15] [--cost-bp 10]`
Quarterly rebalance dates = last weekly bar of each calendar quarter from the SPY grid
(msg 44 "grid uit benchmark-bars"). Each tick: PIT bundles → `scoring.score_universe`
(same code as live) → top-N composite portfolio, equal-weight; 10 bp cost on turnover;
delisted names (price series ends) exit at last available price. Tracks: strategy NAV,
SPY NAV, equal-weight-pool NAV, per-band cohort forward-quarter returns (A/B/C/D/F/VETOED),
tick log (top-5 per tick, pool size). Output: `reports/backtest-<range>.md` + `.json` with
the msg 44 disclosure set (PIT discipline, survivorship caveats, cost model).

### 5.11 `backtest3.py`
`python backtest3.py [--top-n 15] [--calibrate-half A|B] [--cohorts]`
Owner-mode simulation on the PIT data via `formation.py` rules (shared constants).
Walk-forward harness (msgs 49-50): halves 2021-03→2023-12 and 2024-01→2026-06; grid =
gate percentile {10,20,30} × persistence {1,2,3} × exit rank {30,40} (18 options);
pre-registered criterion: beat the equal-weight pool on the blind half with lower turnover;
report both halves, v3 vs v2 vs pool vs SPY, turnover, max drawdown. `--cohorts` (msg 55):
fresh-ranked quality cohorts 1-15 / 16-50 / 51-100 / 101+ per period, no gates.

---

## 6. Reconstruction decisions the history does not fully pin (documented deviations)

1. **Cash-flow-quality veto threshold 25%** — chat pins DAVE 28% / AMRX 28% / IPGP 77% as
   firing; 25% chosen as the lowest round threshold consistent with those.
2. **Extreme-overvaluation exit V-percentile < 5** — chat says "extreme duurte" without a
   number; 5th percentile chosen (clearly "extreme" vs the 20th-percentile entry gate).
3. **Buffett checklist composition** — 13-point total pinned by chat; leg split (7/3/3)
   reconstructed from the upstream agent's scoring blocks cited in msg 30.
4. **Mega-cap DCF growth cap boundary $200B** — chat says "10% voor mega-caps"; upstream
   uses $50B for "large cap"; $200B chosen to match the common mega-cap definition; the
   25% general cap and 85%-of-3-yr-average base are pinned by msg 34.
5. **Pacing default 0.6 s/call** — chat's observed throughput (~11-17 names/min with
   multiple calls each) implies sub-second per-call spacing; the vendored 2 s spacing is
   kept available via `--pace`.
6. **Formation entry pool** — "top-15" candidacy (msg 50 calibrated on top-15) is
   implemented as quality rank ≤ SLOTS; bench admission = passed gate + rank while a slot
   or streak requirement is pending.
7. Chat-reported run outputs (589/443/428 counts, specific grades, backtest returns) are
   period data, not assertions the code must reproduce today.

**Post-reconstruction review fixes (2026-07-31).** Six confirmed findings against the
reconstructed pipeline; the chat is silent on all six because the original agent never hit
(or never reported) them. Each keeps the pinned v2.x semantics and only removes a way the
implementation contradicted them.

8. **Split-adjusted share counts** (§3.2 `splits`, §4.1, §4.3 M/G) — `get_shares_full` is
   split-unadjusted, so a 2-for-1 read as +100%/yr dilution: the >20%/yr hard veto fired on
   any recent splitter for ~a year and the per-share owner-FCF CAGR flipped deeply negative.
   Splits are cached from the existing bar call (no extra Yahoo request, `period="5y"`) and
   every share observation is restated in today's share terms before any trend/per-share
   math. Cache entries and bundles without the key behave exactly as before.
9. **Aligned TTM window** (§4.2) — the newest 4 income quarters and the newest 4 cashflow
   quarters were taken independently, so a name whose statements are one quarter apart mixed
   12-month windows inside one ratio (NI TTM − OCF TTM, owner-FCF/revenue, SBC/revenue). The
   window is now the newest 4 period_ends present in both statements; <4 common → the annual
   fallback, unchanged. The vendored grader keyed everything off one period set.
10. **ROIC cap requires EBIT > 0** (§4.3 Q) — the +1000% cap fired for *any* non-positive
    Greenblatt denominator, handing loss-makers a full ROIC floor factor, top-of-cohort Q/G
    credit and an escape hatch into the §4.4 reinvestor carve-out. The cap is now the
    capital-light/float-financed case only; EBIT ≤ 0 over a non-positive base suspends the leg.
11. **`SHARE_CLASS` suppresses the hard dilution veto** (§4.4) — §4.5 already declares the
    share trend untrustworthy for these names (leg neutral 50, penalty off), yet the same
    trend could still hard-veto them. It no longer can; every other name is unaffected.
12. **Veto layer before integrity-suspend** (§4.4/§4.6) — EBITDA exactly 0 with net debt > 0
    produced INSUFFICIENT instead of the §4.4 leverage veto, because the undefined ratio
    suspended the name before the veto ran. Vetoes are bundle facts and are evaluated first.
13. **Derived reference EV** (§3.3, §4.5) — `yahoo_ev` came from cached `fast_info`, but
    yfinance's FastInfo has no enterprise-value field and the `info`/quoteSummary path is
    banned by the fetch layer and blocked by this environment's proxy (verified:
    SSLError/connection reset). `yahoo_ev` was therefore always None in live runs and the
    v2.1 `EV_GAP` / `SHARE_CLASS` flags (msg 19: 12 EV_GAP names, 4 SHARE_CLASS incl.
    YOU/SGRY/FPS/PLAB) were structurally dead. The same Up-C signal is reconstructed from
    the cache — the listed-class EV `price × latest shares + debt − cash` against the
    all-units own EV — and `ev.yahoo_source` records `"field"` vs `"derived"` so the report
    and datasheet stay honest. A supplied `yahoo_ev` always wins. In the PIT/backtest world
    market cap is *defined* as shares × price, so the derived reference equals own EV and
    the gap is identically 0 — the flags stay silent there, as before.
14. **PIT splits** (§3.6, §5.9) — deviation 8 split-adjusts share counts from the cache's
    `splits`, but PIT bundles had none: EDGAR `dei` counts are as-reported, so a 2:1 split
    read as +100%/yr dilution at every backtest tick and could trip the §4.4 hard veto on
    any splitter. Rather than inferring a factor from the close/adj_close ratio (dividends
    move it smoothly, special dividends jump it), the events are captured exactly — both
    weekly fetches already pass `actions=True`, so Yahoo's "Stock Splits" column costs no
    extra call — stored in the price file and filtered to `<= as_of` before use.
15. **Debt on a repaid balance sheet** (§5.9) — found by running real SEC filings through
    the adapter: EDGAR stops carrying `LongTermDebt*` once a filer repays, so Exelixis and
    Medpace had NO debt tag at their recent balance dates, EV was incomputable, and both
    were suspended as INSUFFICIENT at every tick. Net-cash fortress balance sheets — the
    ones this framework prizes most, and the ones the chat celebrates by name ("net cash,
    inkoop") — were exactly the ones silently dropped from the backtest. A properly tagged
    date (assets AND cash present) with no debt tag now reads as zero, with a 400-day
    carry-forward of any earlier debt first so the error always leans toward more leverage.
16. **Derived gross profit** (§5.9) — same real-filing run: filers need not present a
    gross-profit line, and because the Q gross-margin leg is a REQUIRED metric (§4.6) an
    untagged line suspended the whole name. Gross profit is now derived from revenue minus
    cost of revenue when not tagged directly. A filer that tags neither (Medpace, a CRO
    reporting direct costs under a custom tag) still suspends — honestly, not silently.

**Second price source (2026-08-01).** Yahoo answers HTTP 429 to this box, so the pipeline
could obtain no prices at all — and per `docs/SCORECARD-DESIGN.md` §4.1 a price-less run is a
quality profile and explicitly **not** a verdict, i.e. the entire scorecard withheld.

17. **Declared price basis** (§3.2, §3.6, §5.2, §5.8) — the fetchers gained
    `--price-source {auto,yahoo,stockanalysis}` over a small `pricesrc` layer in which every
    vendor DECLARES what its closes are. stockanalysis.com serves keyless weekly history (10
    years, ~0.3 s/request, browser `User-Agent` required, and only the spans it honors —
    anything else silently returns 52 bars), but its `c` is **split-adjusted to today**, not
    as traded: NVDA's 2024-05-28 bar reads ≈109.6 where ≈1096 traded. Multiplying an
    as-reported dei share count (≈2.46bn pre-split) by such a close understates the market cap
    by the whole split factor — ≈$270bn where the market said ≈$2.7tn — and nothing in the
    numbers says so, which is why the basis is written into every price file and cache entry
    and is **never inferred**. Against a today-basis close the share count is restated into
    today's split terms as well (`scoring.adjusted_shares_series`, already built for deviation
    8); the future-split factor then cancels exactly between the two sides, so the product is
    the true historical market cap **in dollars**. That is an identity, not lookahead: only the
    units the two sides are quoted in change, and they change identically — and ratio metrics
    were indifferent all along, since a factor common to two share observations cancels in the
    trend. Live runs are the easy case: "adjusted to today" *is* today's as-traded price, so
    there the alternative source is a full substitute rather than a compromise. What the
    keyless vendor lacks is a split feed, so its files carry no `splits`: the restatement
    cannot run, `pit.market_cap_at` returns `market_cap_split_unadjusted` for those bundles,
    and both fetchers count them in their closing report — an honest "unverified" instead of a
    silently wrong number. Files from different sources coexist, each declaring its own basis,
    and an absent declaration means `"raw"`, so every pre-existing cache keeps its original
    meaning exactly.

---

## 7. What has and has not been validated

**Offline:** 188 tests over synthetic fixtures cover every module and the cross-module
seams, including one case per finding above.

**Real data:** SEC EDGAR is reachable and was used to validate the point-in-time path
end-to-end on genuine filings for ADBE, EXEL, RMD, MEDP and CRM (five of the chat's
top-10). The adapter reads 19 annual and 73 quarterly periods for Adobe and assembles TTM
through **2026-05-29** — the same May-2026 freshness msg 28 reports — and Adobe does file
under the `Revenues` tag, independently confirming the msg-44 adversarial fix. Deviations
15 and 16 were both discovered by that run, not by review.

**Not validated:** a live Yahoo populate. Yahoo rate-limits (HTTP 429) the datacenter IP
this reconstruction was built on, and yfinance's HTTP layer does not route through the
sandbox proxy, so no end-to-end live grading run has been executed here. The code paths are
unchanged in kind from the ones that produced the 2026-07-29/30 runs on the owner's own
box; they are simply unexercised in this environment. Grades printed by the EDGAR smoke run
are plumbing evidence only — the prices are synthetic and a five-name cohort makes
sector-relative percentiles close to meaningless.
