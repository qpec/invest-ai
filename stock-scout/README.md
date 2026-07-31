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

## Files

| File | Role |
|---|---|
| `universe.py` | FinanceDatabase → `universe.csv` (default / `--broad`) |
| `populate.py` / `augment.py` | paced resumable yfinance cache → `cache/<SYM>.json`, `progress.json`, `failures.log` |
| `reporter.py` / `tg.py` | detached 15-min Telegram progress reporter / stdlib bot client |
| `scoring.py` | **the** decision layer — pure functions shared by live run and backtests |
| `grade.py` | cache → report md + grades json + formation update |
| `formation.py` | frozen v3 owner-mode rules + `formation-state.json` |
| `datasheet.py` | self-contained audit HTML (evidence chain, recompute check, Stage-2 layer) |
| `bt_fetch.py` / `pit.py` | EDGAR companyfacts + weekly prices / point-in-time Bundle adapter |
| `backtest.py` / `backtest3.py` | v2-composite backtest / v3 owner-mode + walk-forward harness |
| `vendor/` | the ratified grader (reference) + hardened yfinance layer (see `vendor/README.md`) |
| `data/stage2-*.json` | qualitative Stage-2 validation layers, picked up by the datasheet |

Tests: `python -m pytest tests/ -q` — fully offline on synthetic fixtures.
