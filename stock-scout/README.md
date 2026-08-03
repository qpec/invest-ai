# Stock Scout — iteration 2, module 1

Value-first stock discovery for the owner's Buffett/Munger/Naval framework: a standalone
pipeline that builds a universe, caches fundamentals, grades every name on the ratified
five-pillar V/Q/G/D/M model (with the v2.1–v2.3 hardening the July 2026 sessions added),
renders an auditable datasheet, and maintains the v3 **owner-mode formation** — the
validated hold-portfolio with buy/sell rules — plus an EDGAR point-in-time backtest layer
that shares the exact same decision code.

> **Recovery note.** The original working tree (built 2026-07-29/30) was lost; this is a
> reconstruction from the complete owner⇄agent chat history. `docs/RECONSTRUCTION.md` maps
> every feature and threshold back to the message that evidences it, and lists the few
> decisions the history did not pin. Chat-reported numbers (589-name universe, +11.5%/yr
> backtest, …) were data outcomes of those days' runs, not constants of the code.

**The system advises and monitors. It never executes trades.** A grade is a research
shortlist, not a buy list; every candidate still passes the Gate.

## Quick start

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cd stock-scout

# 1. Universe: US+NL · IT+Health Care · Mid-cap+  (--broad: all sectors ex Financials/Real Estate, Small-cap+)
python universe.py

# 2. Fundamentals cache (paced, resumable; annual+quarterly in one pass)
python populate.py                       # add --fresh to set the old cache aside as cache-<date>/
nohup python reporter.py &               # optional: 15-min Telegram progress + KLAAR message

# 3. Grade + formation + report
python grade.py                          # writes reports/scout-run-<date>.md + scout-grades-<date>.json,
                                         # updates formation-state.json
python datasheet.py                      # writes reports/datasheet-<date>.html (self-contained audit sheet)
python picks.py                          # writes reports/picks-<date>.html (the shortlist + fragility)
```

Bulk SEC path (no Yahoo needed — the whole universe from one CSV export):

```bash
python picks.py --sec-data <export-dir> --prices <price-cache-dir> --as-of 2026-08-01
```

The thesis engine (needs `ANTHROPIC_API_KEY`; `pip install -r requirements-research.txt`
for filings-text grounding):

```bash
python thesis.py batch --sec-data <dir> --prices <dir>   # draft theses for the top 1%
python thesis.py ratify CROX                             # the Gate — owner ratifies (FR9)
python monitor.py --sec-data <dir> --prices <dir>        # weekly: validate committed theses
```

Telegram (optional): set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`; without them every
send prints to stdout. `grade.py --telegram` sends the report; `reporter.py` reports
long-running populates every 15 minutes (hard requirement from the owner, msg 5).

## Backtests (EDGAR, point-in-time)

```bash
python bt_fetch.py                       # SEC companyfacts + weekly prices → bt_cache/  (keyless, paced)
python backtest.py                       # v2-composite quarterly backtest, band cohorts, 10 bp costs
python backtest3.py --top-n 15           # v3 owner-mode + blind walk-forward validation
python backtest3.py --cohorts            # rank-cohort analysis (1-15 / 16-50 / 51-100 / 101+)
```

The backtest imports the same `scoring.py` the live run uses — the backtest *is* the live
system pointed at the past, with filed-date discipline so nothing is known before EDGAR
knew it.

## The model in one paragraph

Five pillars, sector-relative percentiles, zero magic constants beyond the ratified
reference lines: **V** owner-FCF yield on self-computed EV · **Q** Greenblatt ROIC +
gross-margin level×stability + owner-FCF margin · **G** ROIC-gated revenue and per-share
owner-FCF growth · **D** net debt/EBITDA, self-funding, SBC · **M** share-count trend +
accruals (incl. NCI). Munger's veto layer runs first and *suppresses* (leverage,
cash-destruction, cash-flow quality, serial dilution); data problems surface as flags
(EV gap, share-class/Up-C, float-driven ROIC, low-base growth) instead of silent grades.
Shadow layers that never enter the score: a multi-stage-DCF margin of safety and a
13-point Buffett checklist. The v3 formation then separates buying from selling: quality
(`0.40·Q+0.25·G+0.20·D+0.15·M`) is the engine, price only a gate at the door (V ≥ 20th
percentile), two quarters of evidence before entry, and exit only when quality actually
breaks (veto, rank > 40, extreme overvaluation) — winners are left alone.

## High-level design

Read this section first if you are new to the repo. Everything below is enforced in code,
and every row names the module that enforces it.

### The pipeline, end to end

| # | Stage | Question it answers | In → out | Module |
|---|---|---|---|---|
| 1 | **Universe** | *What is even eligible?* | FinanceDatabase → `universe.csv` | `universe.py` |
| 2 | **Fundamentals** | *What do the filings say?* | yfinance → `cache/<SYM>.json` · SEC CSV export → Bundles | `populate.py` · `secsv.py` |
| 3 | **Prices** | *What does the market say, and in whose share terms?* | vendor → weekly bars + a declared basis | `pricesrc.py` |
| 4 | **Scoring** | *How does this rank against its sector?* | Bundle → V/Q/G/D/M percentiles + vetoes | `scoring.py` |
| 5 | **Scorecard** | *How good is this business, on absolute lines?* | Bundle → 100-point card, band, consensus | `scorecard.py` |
| 6 | **Inversion** | *How would this lose my money?* | Bundle + prices → 7 probes, a verdict, sentences | `inversion.py` |
| 7 | **Formation** | *What do I actually hold?* | grades → buy/sell rules, `formation-state.json` | `formation.py` |
| 8 | **Reports** | *Can I audit every number?* | → markdown, datasheet HTML, picks HTML | `grade.py` · `datasheet.py` · `picks.py` |
| 9 | **Thesis Builder** | *Why would we own this — and what would make us leave?* | top 1% + deep research → draft thesis + summary + report | `thesis.py` · `llm.py` |
| 10 | **The Gate** | *Does the owner ratify it?* | draft → owner conviction + circle fit → committed thesis | `thesis.py ratify` (human, FR9) |
| 11 | **Weekly Monitor** | *Is every committed thesis still true?* | committed theses + fresh SEC data → intact / under review / broken | `monitor.py` |

Steps 4–6 are three **independent** readings of the same Bundle. They are never combined
into one number — see *Two judgements* below. Steps 9–11 are the thesis engine
(`docs/THESIS-DESIGN.md`): the Scout is the starting engine, a thesis is a draft until
the owner ratifies it, and every trigger a thesis carries must be machine-validatable —
metric triggers run mechanically off the same `scoring.evaluate` the grader uses, and
narrative triggers are answered weekly by an LLM with web search (they can summon the
owner to the desk but never fire the sell rule alone).

### Two judgements, kept in separate columns

| | **The scorecard** | **The inversion layer** |
|---|---|---|
| Asks | How good is this business? | How would this break me? |
| Pillar | Buffett | Munger |
| Output | 0–100 points → a band | 7 probe severities → a verdict |
| Scale | absolute anchors, not percentiles | counted severities, never averaged |
| Can it suppress? | yes — §4.4 vetoes | **no** — it names, the human decides |

A name can be **Exceptional and Fragile at once.** That pairing is the most useful thing
the system produces, and both reports show it rather than reconciling it away.

### Key requirements

The rules the code must not break. Each was earned — most from a real defect found by
running the pipeline over real filings.

| # | Requirement | Why | Enforced in |
|---|---|---|---|
| R1 | **Never executes trades** | The system advises and monitors; the Gate is a human step | whole repo — no broker path exists |
| R2 | **Point-in-time discipline** — only facts with `filed <= as_of` | A backtest that reads tomorrow's filing measures nothing | `pit._latest_filed` |
| R3 | **One decision layer** — backtest and live run import the same code | Two copies drift, and the validated one is never the one that runs | `scoring.py`, imported by both |
| R4 | **Price basis is declared, never inferred** | A split-adjusted close × an as-reported share count understates a market cap by the whole split factor | `pricesrc`, `pit.market_cap_at` |
| R5 | **Vetoes run before analysis** | Munger's Hell-No filter: one failure rejects, regardless of upside | `scoring` vetoes → `scorecard` §4.4 |
| R6 | **No price, no verdict** | A price-less run is a quality profile, not a buy case | `scorecard` `NO PRICE` band |
| R7 | **Missing data shrinks the denominator; it never scores zero** | A zero is a judgement; absence is not | `scorecard.available_max` |
| R8 | **Evidence tiers, so a percentage is not read as a ranking** | 97% of 64 measurable points is not better than 94% of 87 | `scorecard.evidence_tier` |
| R9 | **Severities are counted, never averaged** | An average lets a good probe cancel a fatal one — the inversion error itself | `inversion.verdict_for` |
| R10 | **Absent evidence is stated, never read as safety** | Silence about customer concentration is what cost the owner on Cirrus Logic | every probe's `measured` flag |
| R11 | **A finding survives thin evidence** | Absent data may refuse to certify safety; it may never delete a finding | `inversion.inversion`, `consensus_lens` |
| R12 | **Thresholds are declared with provenance and measured coverage** | A line copied from a reference and never measured caught 71% of the universe | `PROBES[...]["provenance"]` |
| R13 | **A quantity the layer cannot attribute is refused, not guessed** | A 20:1 split read as +1,923% dilution; a tagged 100% concentration is a disaggregation total | `max_share_change`, `_CONCENTRATION_TOTAL_ROW` |
| R14 | **No GPL-family runtime dependency** (NFR7) | Licence wall for the wider system | `tools/license_gate.py` |
| R15 | **Tests are fully offline** | Network in a test is a test failure | `tests/` — synthetic fixtures only |
| R16 | **A thesis is a draft until the owner ratifies it** | FR9: conviction and circle fit are asked, never invented — the builder's schema cannot even carry them | `thesis.validate`, `thesis.ratify` |
| R17 | **Every trigger machine-validatable, none price-based** | The thesis drives the monitoring; the stock doesn't know what you paid | `thesis.METRICS`, `thesis.validate` |
| R18 | **Judgement never fires the sell rule alone** | A narrative verdict can only send a thesis to review; breaks need a mechanical trigger or a documented fact | `monitor.check_trigger` |
| R19 | **An unchecked trigger is reported, never read as intact** | No API key ≠ no risk; silence is not safety | `monitor` UNCHECKED reporting |

**Architecture revision (2026-08-03, journaled in `docs/THESIS-DESIGN.md` §1):** the
2026-07-08 "no LLM in the scheduled runtime" lock is lifted by owner decision. The LLM
transport is a hand-rolled stdlib client (`llm.py`, the `tg.py` pattern), default model
`claude-opus-5`.

## Files

| File | Role |
|---|---|
| `universe.py` | FinanceDatabase → `universe.csv` (default / `--broad`) |
| `populate.py` / `augment.py` | paced resumable yfinance cache → `cache/<SYM>.json`, `progress.json`, `failures.log` |
| `reporter.py` / `tg.py` | detached 15-min Telegram progress reporter / stdlib bot client |
| `pricesrc.py` | price vendors, each DECLARING the share terms of its closes (`raw` / `split_adjusted_today`) |
| `scoring.py` | **the** decision layer — pure functions shared by live run and backtests |
| `scorecard.py` | the Owner's Scorecard — 100 absolute points, bands, evidence tiers, consensus |
| `inversion.py` | the Munger layer — 7 fragility probes → a verdict and its sentences |
| `grade.py` | cache → report md + grades json + formation update |
| `formation.py` | frozen v3 owner-mode rules + `formation-state.json` |
| `datasheet.py` | self-contained audit HTML (evidence chain, recompute check, Stage-2 layer) |
| `picks.py` | self-contained picks HTML — the shortlist, with fragility beside every score |
| `llm.py` | stdlib Claude Messages client (web search, strict tools, pause_turn, refusal fallbacks) |
| `thesis.py` | the Thesis Builder: top 1% → deep research → draft thesis + summary + report; `ratify` = the Gate |
| `monitor.py` | the Weekly Monitor: committed theses validated against their own triggers (FR7) |
| `bt_fetch.py` / `pit.py` | EDGAR companyfacts + weekly prices / point-in-time Bundle adapter |
| `secsv.py` | bulk SEC CSV export → companyfacts shape → Bundles (1,904 names in ~20 s) |
| `backtest.py` / `backtest3.py` | v2-composite backtest / v3 owner-mode + walk-forward harness |
| `vendor/` | the ratified grader (reference) + hardened yfinance layer (see `vendor/README.md`) |
| `data/stage2-*.json` | qualitative Stage-2 validation layers, picked up by the datasheet |

Design docs: `docs/RECONSTRUCTION.md` (chat → code, plus 19 documented deviations),
`docs/SCORECARD-DESIGN.md` (why the percentile composite was replaced),
`docs/INVERSION-DESIGN.md` (the Munger layer, and §8 on what its first cut got wrong).

Tests: `python -m pytest tests/ -q` — 671 tests, fully offline on synthetic fixtures.

## Validation status

The point-in-time path is validated against **real SEC filings** (Adobe, Exelixis, ResMed,
Medpace, Salesforce): the adapter reads Adobe's 19 annual and 73 quarterly periods and
assembles TTM through May 2026, the same freshness the original v2.2 run reported. Two real
defects surfaced only there — companies that had *repaid* their debt, and companies that
never tag a gross-profit line, were both being dropped from every backtest tick — and both
are fixed (`docs/RECONSTRUCTION.md` §6.15-16).

A live Yahoo populate has **not** been run here: Yahoo rate-limits this container's IP.
Nothing about the fetch layer changed in kind from the code that produced the original
runs, but treat the first live run on your own box as the real smoke test.
