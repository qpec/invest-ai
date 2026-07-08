# stock-agentcy — Functional Architecture Elaboration

**Status:** Approved design. Synthesized 2026-07-08 from a three-draft / three-judge panel (drafts: data-model-first [winning skeleton, ranked first by all three judges], loops-first, behavior-first), with all judge-identified violations fixed and cross-draft gaps resolved. Owner decisions of 2026-07-08 incorporated: **FR13 benchmark = S&P 500 TR measured in EUR** · **balance defaults as §E.3** · **ETFs default to outside-framework** · **daily letter carries no portfolio value**.

**Scope:** functional design only; technology/runtime parked. References only adopted tooling: hardened yfinance, pandas+scipy clustering, quantstats (pinned, quarterly-quarantined), TradingView-Screener (human-run), FinanceDatabase universe file (direct read, §H). Elaborates the approved baseline (`docs/plans/2026-07-08-functional-design-baseline.md`, FR1–FR14 / NFR1–NFR7) under the Constitution (`CLAUDE.md`).

**Field notation:** `name : type {allowed values} — source`, where source ∈ **owner** (typed by the owner; never generated — all FR9 fields), **computed**, **fetched** (adopted data stack), **config** (owner-adjustable default; changes journaled).

**Global invariants:**
1. All objects append-only or versioned; nothing destructively edited (NFR4).
2. Every thesis state transition and every owner decision produces a JournalEntry (FR8).
3. No component ever produces an execution instruction — advice only (FR11).
4. Cost basis (`avg_open_price`) exists for record-keeping only; it is a **forbidden input** to any advice computation (FR7).
5. A **downward price move is never an invalidation trigger.** Price appears in monitoring only as buy-opportunity detection and the optional upward euphoria trigger (§B).
6. Freshness gate: no trigger may FIRE on stale/empty data; stale checks return STALE and are reported as **suspended, never passed** (NFR1, NFR6).
7. Benchmark quarantine is structural: the daily/weekly/event generators have no read path to the benchmark series — not a suppressed section, an absent input (FR13).

---

## 0. The Loop Spine

The system is four scheduled runs plus three human-triggered runs. Nothing else executes. Every data object exists because a named run reads or writes it.

| Run | Trigger | Reads | Writes | Reaches owner |
|---|---|---|---|---|
| **Daily loop** | once per market day, after US close | Snapshot, PriceCache, Register (daily-cadence triggers), config, FX | Daily letter, RunLog, trigger check-states | Daily letter (short) |
| **Weekly loop** | **Saturday morning** — deep review happens when nothing can be traded impulsively | Snapshot, PriceCache (1y), FundamentalsCache (refreshed), full Register, Journal open loops, Watchlist, StudyQueue | Weekly review, RunLog, FundamentalsCache, StudyDigest | Weekly review (deep) |
| **Event check** | earnings/filing/mgmt event detected or owner-injected (FR6) | affected thesis + full trigger set, fresh fundamentals for that ticker | Event report or Alert, RunLog | Alert, or one line in next daily letter |
| **Quarterly honesty check** | once per quarter | Snapshot history, PriceCache, BenchmarkSeries (quarantined store), Journal entries at review horizon | Quarterly report, journal reviews, RunLog | Quarterly honesty report |
| **The Gate** (human) | owner submits a candidate | WatchlistItem, FundamentalsCache, Mirror balance pre-check | Thesis (draft), JournalEntry, Watchlist update | Gate verdict document |
| **Scout session** (human, §H) | owner decides to look for ideas | Universe file, screen recipes (config) | WatchlistItem (human-picked only, FR14) | Screen results, human-read, never stored |
| **Owner decision** (human) | alert response, amendment, journal review | Alert, Thesis | Thesis version/status, JournalEntry | Confirmation |

**Data objects:** Snapshot, PriceCache, FundamentalsCache, Thesis, Trigger, Alert, JournalEntry, WatchlistItem, BenchmarkSeries (quarantined), Report archive, and **RunLog** — every run records which inputs it used, the staleness of each, which checks ran, what was decided, and what was emitted. RunLog makes "what did the system know and when" a first-class auditable object (NFR4); journal entries pin `inputs_ref` to the RunLog of the run that informed them.

---

## A. Thesis Register

One living document per framework holding (and per gate-approved watchlist candidate). The Register is the source of truth; the Watchdog reads only from it.

### A.1 Thesis schema (FR2 made concrete)

**Identity & lifecycle:** `thesis_id` (immutable, e.g. `TH-VEEV-001`) — computed · `ticker` — owner · `instrument_name` — fetched · `status` {draft, intact, under_review, broken, retired} — computed (A.2) · `origin` {gate, backfill} — computed · `version` — computed · `created_at`, `activated_at` — computed · `review_deadline` (null unless under_review) — computed.

**Constitution content — every field mandatory before `status` may leave `draft`:**

| Field | Type / rule | Source |
|---|---|---|
| `business_model_2s` | text, **hard limit 2 sentences** (system rejects longer) | **owner** |
| `moat_types` | list {network_effects, switching_costs, cost_advantage, brand_trust, regulatory_barrier}, min 1 | owner |
| `moat_evidence` | text; ≥1 observable fact per selected moat type | owner (Gate dossier supplies candidate facts) |
| `owner_earnings` | `fcf_ttm` — fetched · `fcf_per_share_ttm` — computed (`get_shares_full` resampled) · `fcf_margin_ttm` — computed · `narrative` — owner | mixed |
| `valuation_anchor` | `metric` {**P_FCF (default)**, P_E, P_S} — owner · `value_at_purchase` — computed · `fair_band_low/high` (multiple range) — owner · `denominator_note` — owner. **EV-based metrics are excluded in v1**: converting an EV band to a daily per-share check needs net-debt machinery that costs more than it adds now; revisit only if a thesis genuinely cannot be anchored per-share. | mixed |
| `conviction` | {high, medium, low} | **owner — never generated (FR9)** |
| `mgmt_trust` | {trusted_owner_operator, trusted_professional, neutral, distrust} + note. `distrust` at the Gate = Hell-No HN3 fail; **post-activation the owner may downgrade to `distrust` at any time** — doing so auto-opens an owner-initiated review (A.2). Trust is an ongoing condition, not a purchase-time checkbox. | **owner (FR9)** |
| `circle_fit` | {core, edge} + note (which competence domain) | **owner (FR9)** |
| `time_horizon` | **`10y_plus` only.** Anything shorter is, per the Constitution, speculation — the Gate rejects it (and it would contradict the mandatory 10-year statement). | owner |
| `ten_year_statement` | text, first person: "would I hold if the market closed for a decade, and why" | **owner** |
| `triggers` | list<Trigger> (§B), **min 2, max 5** — fewer is unfalsifiable, more is noise | owner-committed, system-assisted drafting |
| `status_buy_flag` | bool + note — carried from the Gate (C.5) | computed + owner |

**Rules:** `conviction`, `mgmt_trust`, `circle_fit`, `ten_year_statement` have no defaults and cannot be copied from a prior thesis. The system asks; the owner answers; blank blocks activation. **Annual re-affirmation (judgment anti-staleness):** at each thesis anniversary the weekly review asks the owner to re-affirm conviction, mgmt_trust and circle_fit (one prompted question); three consecutive skips escalate to the weekly headline. Fundamentals get weekly refresh — judgment gets at least yearly refresh.

### A.2 Lifecycle / status transitions

```
draft ──(all FR2 fields + position in Snapshot / backfill confirmed)──▶ intact
intact ──(any Trigger FIREs, or owner-initiated review incl. mgmt_trust
          downgrade — always journaled)──▶ under_review   [deadline = +7d config]
under_review ──(owner refutes with written evidence)──▶ intact (trigger re-arms)
under_review ──(owner confirms)──▶ broken ──▶ sell advice (cost basis ignored, FR7)
any ──(position closed / owner exits)──▶ retired (immutable)
```

- `broken` is terminal for the thesis, not the position: holding anyway is journaled `advice_rejected` and re-flagged **every weekly review** until sold or a genuinely new thesis (new `thesis_id`, full Gate re-run) replaces it. A broken thesis is never repaired in place — that would be commitment-bias laundering. `broken → intact` does not exist.
- Deadline passes with no decision → auto JournalEntry `alert_ignored` + escalation in every daily letter (FR8: ignoring is allowed, but recorded). See §D.6 for pause mode.
- There is **no autonomous "material concern" transition**: the system can only move a thesis to `under_review` via a pre-committed trigger. Anything else the system notices is information in a report, never an alarm.

### A.3 Versioning, goalpost guard, re-anchoring (NFR4 + Munger)

- Every post-activation mutation creates `version+1` with per-field diff, owner reason, actor, timestamp, linked JournalEntry.
- **Trigger-loosening guard:** loosening (weaker threshold, longer persistence, deletion) is allowed only while `status = intact` — never during `under_review` (you may not move the goalposts while the ball is in the air; during review, `revise` is possible only after an explicit `refute`). If the trigger's metric is within 10% of its threshold at loosening time, a **drift flag** is set (never blocks — advise-only — but makes it impossible to do quietly). Every relaxation prints in the weekly review for 4 weeks. Tightening and adding triggers are always free.
- **Fair-band re-anchoring ritual:** the band may be revised only at the thesis anniversary review or in the wake of an earnings event-check; always a version bump with journaled reason and the same 4-week echo; forbidden while `under_review`. Bands never auto-update — the *denominator* refreshes weekly (E.4), the *multiple range* is owner judgment.

### A.4 Worked micro-example

```
TH-VEEV-001  VEEV  intact  v2  origin: gate
business_model_2s: "Veeva sells the system-of-record SaaS suite (CRM, quality,
  regulatory, clinical) that life-sciences companies run their FDA/EMA-regulated
  core processes on. Customers pay recurring subscriptions and effectively cannot
  leave, because migrating a validated GxP system means re-validation."
moat: [switching_costs, regulatory_barrier] — retention >115%; validated-system
  replacement = multi-year compliance project; 20/20 top pharma are customers.
owner_earnings: fcf_ttm ≈ $1.1B · fcf/share ≈ $6.7 · margin ≈ 40% · "subscription
  cash up front, negligible capex, net cash — nearly all OCF is owner earnings."
valuation_anchor: P_FCF · at purchase 30.0 · fair band 25.0–35.0
conviction: high   mgmt_trust: trusted_owner_operator (founder-CEO, large stake)
circle_fit: core (healthcare SaaS)   time_horizon: 10y_plus
ten_year_statement: "Yes. Life-sciences regulation only accumulates; the vendor
  that owns the validated record layer compounds with the industry."
triggers: T1 growth_floor rev YoY <10% (2q) · T2 margin_erosion FCF margin <30%
  · T3 owner_attested: founder-CEO departs · T4 dilution shares +3%/12m
v2: T4 2%→3% ("SBC settle-cadence noise", journaled JE-0007, drift flag: no)
```

---

## B. Trigger taxonomy

### B.1 Trigger schema

`trigger_id` — computed · `type` (B.2) — owner · `statement` : one falsifiable sentence, owner's words ("If X, the reason I own this is gone") — **owner** · `metric` + `comparator` + `threshold` — owner · `persistence` {single_observation, 2_consecutive_quarters, ttm} — owner, default per type · `check_method` {automated, prompted} — computed from type (**testable ≠ automatable; it means falsifiable, pre-committed, and actually checked**) · `data_source` {yf_price, yf_quarterly_statements, yf_shares_full, yf_officers, yf_calendar, fx, owner_attestation} — computed · `cadence` {daily, weekly, event, dated} — computed · `status` {armed, fired, stale, retired} · `last_checked`, `last_result` {PASS, FIRE, STALE, UNVERIFIABLE} · `fired_at`, `resolution` {confirmed_broken, refuted, revised}.

All automated checks run through the hardened yfinance layer: cached + paced, **emptiness detection on every field** (empty → STALE, never PASS/FIRE), shares via `get_shares_full` resampled + dedup'd (NFR6).

### B.2 The seven trigger types

| # | Type | Testable form | Source | Cadence | Check |
|---|---|---|---|---|---|
| 1 | `growth_floor` | revenue (or committed line) YoY < X% · default 2 consecutive quarters | statements | weekly + event | automated |
| 2 | `margin_erosion` | FCF margin TTM < X% or gross margin TTM < X% (owner picks the line that proxies the moat's pricing power — automatable moat proxies live here) | statements | weekly + event | automated |
| 3 | `balance_sheet_safety` | net debt/EBITDA > X, or cash < X quarters of burn | statements | weekly + event | automated |
| 4 | `dilution` | shares outstanding trailing-12m growth > X% (default 3%) | shares_full | weekly | automated |
| 5 | `owner_attested_event` | pre-committed **binary question** put to the owner (at each earnings event; weekly if flagged urgent): non-automatable moat proxies ("NRR < 110%?"), management/trust events (named person departs; restatement; related-party dealing), thesis-specific events ("loses exclusivity on X"). The weekly `companyOfficers` diff is a **tripwire that queues the question — a tripwire, not truth.** The owner is the sensor; the system is the scheduler and record-keeper. | owner_attestation (+officer-diff tripwire) | event / weekly | prompted |
| 6 | `milestone` (dated) | "by {date}, {metric} ≥ {value}" — checked at first earnings event on/after the date | statements + calendar | dated | automated or prompted |
| 7 | `valuation_euphoria` (optional, **upward only**) | anchor multiple > k × `fair_band_high` (default k = 1.5) → **trim review**, thesis stays `intact` (expensive ≠ invalidated — the only price-linked trigger, and only upward) | price + weekly denominator | daily | automated |

**Restated:** there is no trigger type for a price decline. A drawdown with an intact thesis routes to the buy-opportunity check (E.4), never to an alert.

### B.3 Firing, escalation, storms, revisions

1. FIRE → `thesis: intact → under_review` (same instant), `review_deadline = +7d`; Alert per G.3.
2. Owner options (each journaled): `confirm_broken` → sell advice without cost basis; `refute` → written evidence, back to intact; `revise` → only after refute (goalpost guard A.3). Type 7 exception: trim-review advice, no status change.
3. No decision by deadline → `alert_ignored` auto-journaled; heads every daily letter until resolved.
4. **UNVERIFIABLE is never OK:** a prompted question skipped twice, or an automated check stale, reports UNVERIFIABLE/STALE in every review; **3 consecutive unverifiable weeks escalate to the weekly headline.** Suspended ≠ green.
5. **Alert storms (correlated stress):** multiple fires on one day → a single bundled alert, items ranked by position weight, one shared deadline. A market-wide drawdown across intact theses is, by construction, an *opportunities* section — the calmest week the system has.
6. **Data revisions:** every verdict is pinned to data-as-fetched (`RunLog.inputs_ref`). If Yahoo later revises figures such that a past verdict would have differed, the weekly review notes it ("Q1 FCF revised; T2 would not have fired on revised data") — verdicts are never retro-fired or retro-cleared; armed triggers simply evaluate current data at their next check.

---

## C. The Gate

Nothing reaches the portfolio without passing every step in order: cheap human filters before expensive analysis (Munger before Buffett), owner judgment before drafting, drafting before verdict.

### C.1 Watchlist (entry — FR14)

`WatchlistItem`: `ticker` — owner · `added_at` — computed · `idea_source` {own_research, scout_screen, reading, referral} — owner · `one_line_why` — owner · `stage` {raw, gate_approved_waiting} — computed. **Cap 10 raw items · 90-day expiry** (expiry auto-journaled `watchlist_event`, no reasoning demanded — ideas must earn a Gate run or die quietly; a FOMO drain, not a chore).
- Entry is human-triggered only (FR14). Tooling-assisted path = the Scout (§H): human-run screens, human-read results, hand-picked tickers.
- `raw` items get **zero automation** — no prices, no monitoring, no "your watchlist moved" notes.
- `gate_approved_waiting` items carry an activated draft thesis and exactly two armed price checks (C.6/E.4).
- **Re-pitch confrontation:** re-adding a previously rejected ticker surfaces the original `gate_pass` journal entry verbatim before the Gate will run again.

### C.2 Step 1 — Circle of competence (owner, minutes)

Owner writes `business_model_2s` (2-sentence hard limit) and names the moat in one phrase **from memory, without research**; answers `circle_fit` {core, edge, outside}. `outside` or can't-write-it → verdict PASS (rejected), journaled `outside_circle`. No exceptions for upside.

### C.3 Step 2 — Hell-No filter (FR3)

Five binary tests; **one FAIL = REJECT, no override path** — the absolutism is what makes the veto work. Remaining tests still recorded for the journal.

| Test | Question | Evidence |
|---|---|---|
| HN1 Leverage | instrument embeds leverage (CFD, leveraged ETF, margin) or purchase requires borrowing? | fetched instrument type; owner attestation |
| HN2 Understandability | valuing it needs more than ~5 core assumptions? | owner attestation + the 2-sentence artifact |
| HN3 Management | any reason to distrust management? (prefer owner-operators with skin in the game) | fetched facts (insider ownership, officers) as evidence; **judgment is owner's (FR9)** |
| HN4 Fad | real present-day revenue and FCF, or narrative? | fetched TTM revenue/FCF (emptiness-checked); owner attestation |
| HN5 Fees | fee structure, 2-and-20, expense ratio, structure requiring frequent trading? | fetched expense/instrument data; owner attestation |

Rejections stay visible: the quarterly review reads `gate_pass` entries **on the stated reason only, never on foregone price appreciation** — a process-correct rejection that later "missed a winner" is graded GOOD PROCESS (the fee for never taking the catastrophic loss).

### C.4 Step 3 — Buffett dossier (system)

Assembled from the hardened data layer, every number freshness-stamped, empty statements declared: (1) moat-evidence candidates (margins & 5y trend, retention if owner-supplied); (2) owner-earnings picture (FCF TTM + 5y, FCF/share on resampled shares, SBC & dilution trend, net cash/debt); (3) valuation-anchor material (chosen per-share metric: current + 5y range — the dossier proposes history, **the owner sets the band**); (4) 10-year framing questions; (5) status-buy heuristic flag (12m price +100% or owner-admitted media darling) — an input to Step 4, not a veto. Missing/empty fundamentals → the Gate **pauses**; no verdict on absent owner-earnings data.

### C.5 Step 4 — Owner judgment (FR9, sacred)

The system asks; only the owner answers; no defaults, no suggestions: `conviction` · `mgmt_trust` + note · `circle_fit` confirmation · `ten_year_statement` · the status question verbatim: *"Would you still buy this if you could never tell anyone you owned it?"* If the heuristic flag is set and the owner hesitates, `status_buy_flag = true` is written into the thesis and printed in the verdict. **The system never constrains conviction** — sizing consequences live in E.3, labels stay the owner's.

### C.6 Step 5 — Thesis drafting → verdict

Thesis per A.1 (system fills fetched/computed fields; owner writes owner fields and commits 2–5 triggers; system may propose trigger *templates*, thresholds are owner-set).

| Verdict | Meaning | Consequence |
|---|---|---|
| `BUY_READY` | framework-clean, price inside or below fair band | advice text incl. suggested max initial weight (E.3). If `status_buy_flag` is set, BUY_READY requires the owner's written rebuttal of the flag first (friction by design — flag + rebuttal, not a separate verdict state). Owner executes or not; thesis activates when the position appears in a Snapshot. Non-execution after 30 days → prompt: journal `advice_rejected` or move to WATCH. |
| `WATCH` | business passes, price above fair band | thesis stays `draft`; two armed daily checks: **fair-entry** (price ≤ `fair_band_high` × denominator — "now fairly priced", Buffett's wonderful-business-at-fair-price line) and **opportunity** (E.4 — "on sale"). |
| `PASS` | rejected at any step | journaled with step + reason class {outside_circle, hell_no_HN1..HN5, no_moat_evidence, owner_earnings_absent, owner_declined}. |

**Approval expiry:** BUY_READY/WATCH lapse after **12 months** — a stale thesis is not a thesis; re-approach = fresh Gate run. **Displacement rule:** at 15 framework positions, a BUY_READY verdict must name which existing holding this candidate beats, and why (Munger opportunity cost made mechanical).

**Backfill Gate (FR1, disambiguated):** existing holdings without a thesis run the **full Gate, Steps 1–5 including the Buffett dossier**, with two differences: no price verdict (the position is already held) and outcomes {`activate_backfill`, `no_thesis_exists`}. `no_thesis_exists` = the honest admission there is no thesis → treated as broken → sell advice (cost basis ignored). **Bootstrap sequencing:** backfill queue ordered by position weight, largest first; suggested pace one Gate per week; until backfilled a holding is monitored for balance only and flagged weekly (no fake triggers).

---

## D. The Watchdog

Reads only the Thesis Register and config. Never scans open-ended news. Four cadences + interaction contract + pause mode.

### D.1 Daily loop

- **Inputs:** latest Snapshot (any age — NFR1); daily closes for held + gate-approved tickers + FX pairs; Register; config; weekly-computed denominators.
- **Checks:** (1) type-7 euphoria per armed trigger; (2) buy-opportunity & fair-entry scans (E.4); (3) balance drift vs bands (E.3), last snapshot marked-to-market; (4) unresolved items (open reviews past deadline, alert_ignored, broken-but-held); (5) data health (snapshot age, per-ticker price staleness); (6) earnings within 21 days → information-only preview line.
- **Outputs:** daily letter (G.1). Default and celebrated: **"No action needed"** (FR4), with the no-action streak counter. Trigger fires route to the Alert channel.
- **Degradation:** stale snapshot → banner "positions as of {date}"; per-ticker stale price → euphoria STALE (cannot fire), opportunity lines suppressed for that ticker; **>50% tickers stale → "market data degraded"**, checks 1–3 suspended and say so; total failure → the letter still sends: "Data sources unavailable since {t}; last known state; no checks performed. Nothing is wrong; I just can't see."

### D.2 Weekly loop (Saturday, FR5)

- **Inputs:** daily inputs + quarterly statements per holding (emptiness-checked), `get_shares_full` refresh, `companyOfficers` diff, 252-day return history (all invested positions incl. outside-framework), earnings calendar.
- **Checks:** (1) fundamentals refresh → recompute FCF TTM/margins/dilution; refresh `opportunity_price` and `fair_entry_price` denominators; (2) full re-test of every armed automated trigger + queue prompted questions; (3) thesis re-validation per holding: status, **trigger headroom table** ("growth 14.2% vs floor 10% — headroom 4.2 pts"), anchor multiple vs band; (4) balance review per E.3 + **hidden-concentration (FR12) per E.5**; (5) officer-diff tripwire → queued question; (6) FR1 sweep → backfill flags; (7) anniversary re-affirmations due (A.1); (8) Study digest (F.3).
- **Outputs:** weekly review (G.2); prompted-question queue; alerts for fires.
- **Degradation:** empty statements → holding's fundamental triggers STALE, printed as "suspended, not passed"; <120 days return history → own cluster + flag; clustering failure → last week's clusters, tagged stale.

### D.3 Event checks (FR6)

- **Sources:** (a) earnings date reached (calendar checked daily; **fallback: statement-fingerprint change detected in the weekly refresh** — late detections marked "detected late" for audit); (b) owner ad-hoc event entry — the owner is a first-class sensor; (c) officer-diff escalation.
- **Checks:** immediate, single-holding: fresh statements (bypass cache, still paced); all armed triggers for that thesis; all prompted questions queued with the event named.
- **Outputs:** event report (archived); quiet outcome = one line in the next daily letter ("{TICKER} earnings checked; {n}/{n} triggers pass; no action needed") — no extra ping. Fires → Alert.
- **Degradation:** post-earnings data lag → retry daily for 7 days; prompted questions to the owner don't wait for the data.

### D.4 Quarterly honesty check (FR13, quarantined)

- **Inputs:** snapshot history (with dated external flows, E.1), adjusted price history, FX history, benchmark series (`^SP500TR` × USD→EUR — the quarantined store), quantstats pinned.
- **Method:** daily portfolio EUR return series reconstructed from snapshots × adjusted closes × FX; external flows handled **time-weighted (Modified Dietz per inter-snapshot period, geometrically linked)** so deposits never masquerade as alpha; inception = first snapshot date. Dividends: adjusted closes embed them in returns; dividend cash arriving in snapshots is an internal flow (not external). Stats: CAGR, max drawdown, volatility, Sharpe/Sortino + `qs.reports.metrics` vs benchmark, both series in EUR, labeled **indicative, not authoritative**.
- **Outputs:** quarterly honesty report (G.4) + the journal review batch (F.2).
- **Degradation:** quantstats breakage → **four hand-computed stats** (period return, vs-benchmark simple return, max drawdown, volatility) — the honesty question still gets answered. Snapshot gaps >7d → periods marked approximate; >30d → relative-performance headline withheld ("better silent than wrong").

### D.5 Owner interaction contract

Every owner-facing ask is a first-class object: stable ID, enumerated reply options, free-text where committed. Prompted trigger questions accept exactly {yes, no, can't-verify + note}; alerts accept exactly the three options of B.3; Gate/journal fields accept their schema. Malformed or partial replies → one re-prompt, then counted unanswered. Unanswered pre-fire prompts follow the UNVERIFIABLE escalation (B.3.4); unanswered alerts follow the `alert_ignored` path. Every answer is journaled with its ask-ID. This contract is the system's most-used interface and is deliberately boring: binary where possible, pre-committed everywhere.

### D.6 Pause mode (owner absence)

Owner declares an absence window (journaled on/off). During it: alert decision windows freeze (no `alert_ignored` auto-entries), alerts still deliver, daily letters optional (config), weekly reviews continue. A vacation must not pollute the FR8 process record with fake "ignored" decisions.

---

## E. Portfolio Mirror

### E.1 Source-agnostic snapshot ingestion

`Snapshot`: `snapshot_id`, `as_of`, `source` {api_pull, manual_export, manual_entry}, `positions`, `cash_balance`, **`external_flows`: list of {date, amount, direction} since the previous snapshot — owner-confirmed at ingest** (feeds D.4 Modified Dietz).

**Canonical contract** — any adapter (future eToro API, CSV export parser, manual form) produces identical per-position fields; the rest of the system cannot tell sources apart: `symbol` (mapped to yfinance ticker via owner-maintained `symbol_map`) · `instrument_type` {stock, etf, crypto, copyportfolio, cash} · `quantity` · `avg_open_price` (**record-keeping only, forbidden in advice — FR7**) · `native_currency` · `market_value_native` · `market_value_eur` (FX pairs derived from the native currencies present: `{CUR}EUR=X` daily closes, cached; same source converts the benchmark) · `weight` · `framework_status` (E.2) · `thesis_id` · `leverage` / CFD metadata.

**Leverage tripwire:** any position with leverage > 1 or `instrument_type` CFD fires an immediate Hell-No violation alert — the Constitution's leverage veto enforced continuously, not just at the Gate.

**Operating contract (manual mode):** expected export cadence weekly before the Saturday run + after any trade. Staleness ladder: prices >3 trading days → trigger evaluation suspended (honest wording); snapshot >14 days → weights marked stale; >30 days → balance advisory suspended + fresh export requested. **The daily letter itself is never skipped.**

**Reconciliation on every snapshot:** new ticker without thesis → `backfill_pending` (crypto/copyportfolio/ETF → prompt owner once to designate `outside_framework`); disappeared ticker → prompt to journal the close; quantity change → journal prompt (add/trim). Closes the FR8 loop for trades executed off-system.

### E.2 Framework vs outside-framework (FR10)

- `framework`: active thesis; fully monitored.
- `backfill_pending`: equity without thesis — flagged weekly until the backfill Gate (C.6) resolves it.
- `outside_framework`: crypto, copyportfolios, **and ETFs by default (owner decision 2026-07-08)** — visible in all balance views, **included in concentration/cluster math (real risk is real), excluded** from thesis monitoring, triggers, and buy-opportunity logic. No thesis pretension. Revisit the ETF default only if a thesis-worthy ETF need actually emerges.

### E.3 Balance model — defaults approved 2026-07-08 (all config; changes journaled)

| Parameter | Default | Behavior when breached |
|---|---|---|
| `cash_band` | 5–15% | below: "buying power thin"; above: "cash idle — no forced deployment" (never "you must invest") |
| `max_position_soft` / `hard` | 15% / 20% | soft: "winner has run — review, no obligation"; hard: trim-review advice. Winners run; the hard cap is the survival line. |
| `max_sector_weight` | 50% (informational) | coarse label check (yfinance sector, owner-overridable); the cluster check is the binding safeguard — sector labels lie, correlations don't |
| `max_cluster_weight` | 40% of invested (ex-cash) | "cluster {label} is {w}% — are these separate bets?" |
| `min_effective_bets` (FR12) | **N_eff ≥ 4.0, cluster-weight basis (1/Σw_c²)** — position-basis N_eff shown as context, no second floor | "your {n} positions are behaving like {N_eff} bets" |
| `position_count_band` | 10–15 framework | <8 "concentration beyond mandate — deliberate?"; >15 "diworsification" + displacement rule active (C.6) |
| `outside_framework_cap` | 10% | weekly advisory flag (FR10: visible, not forbidden) |
| `buy_opportunity_discount` | 20% | E.4 |
| `alert_decision_days` | 7 | B.3 |

### E.4 Buy-opportunity & fair-entry checks

Weekly, per intact thesis and gate-approved item: `opportunity_price = (1 − discount) × fair_band_mid × denominator_per_share` — the anchor is a **multiple**, the denominator refreshes itself weekly, so the threshold never rots as fundamentals grow. WATCH items additionally arm `fair_entry_price = fair_band_high × denominator_per_share`.
Daily: cheap comparisons. Fair-entry hit (WATCH only): *"{TICKER} has entered your fair band ({multiple}× vs {low}–{high}×). Wonderful business, fair price — the Gate approved it; the price now agrees."* Opportunity hit (intact holdings and WATCH): *"{TICKER} trades at {multiple}× vs your band {low}–{high}× — a ≥20% discount to your own anchor. Thesis intact ({n}/{n} triggers pass). Great businesses on sale is the plan working."* Cash-band status alongside; invitation framing; no urgency language, ever.

### E.5 Hidden-concentration method (FR12)

Daily returns **in local currency** (a common EUR/USD factor must not fuse all USD holdings into one fake cluster), 252-day lookback, ≥120 overlapping days (else own cluster + flag). Distance `sqrt((1−corr)/2)`, average linkage, `fcluster(criterion="distance", t=sqrt((1−0.7)/2)≈0.387)` — positions cluster when average correlation exceeds 0.7 (config). `N_eff = 1/Σw_c²` over cluster weights (invested, ex-cash, **incl. outside-framework**). Weekly review: cluster membership table, cluster weights, N_eff (cluster + position basis), correlation matrix. Zero new dependencies.

### E.6 FR13 benchmark (approved 2026-07-08)

**S&P 500 Total Return, measured in EUR** (`^SP500TR` × daily USDEUR; portfolio series likewise EUR). Rationale: (1) **PFIC reality** — under the owner's tax residency, UCITS trackers are punitively taxed; the realistic passive counterfactual is a US-domiciled fund; (2) opportunity-set match — the book is predominantly USD US large-cap; (3) EUR on both sides keeps FX out of the process comparison. Documented alternative: VT (US-domiciled total-world) in EUR. One benchmark only; config change requires a journaled reason.

---

## F. Decision Journal + The Study

### F.1 JournalEntry schema

`entry_id` (append-only, immutable) · `timestamp` · `decision_type` {buy, add_to_position, trim, sell, hold_after_review, advice_rejected, alert_ignored, gate_verdict [pass/watch/buy_ready], trigger_resolution [confirmed_broken/refuted/revised], thesis_revision, watchlist_event [add/expire], designation_or_config [outside_framework/config_change]} — twelve types with subtypes, pruned for NFR5 · `ticker`/`thesis_ref` (`thesis_id@version`) · `system_recommendation` (verbatim at that moment) · `owner_action` {followed, overridden, no_action} + `decision_statement` · `reasoning_at_the_moment` — **owner, mandatory for owner-initiated types; captured before the outcome is known** · `expected_outcome` + **`falsifier`** ("what would prove this decision wrong") · `review_horizon` (default 1y; `too_early` re-queues one horizon) · `inputs_ref` (RunLog pin: exactly which data this decision saw) · `process` {followed, deviated} + **mandatory note when deviated** (binary — honest, gradeable immediately; letter grades were precision theater) · `outcome_grade` {good, neutral, bad, too_early} + note — filled **only at review**, judged against `expected_outcome`/`falsifier` and thesis validity, never raw price · `emotional_note` (optional — Munger's cheapest overconfidence detector).

Auto-created entries: `alert_ignored`, `watchlist_event[expire]` (no reasoning demanded), `gate_verdict[pass]` (every rejection is a decision).

### F.2 Process-vs-outcome review

Batched into the quarterly report (one honest hour per quarter). The 2×2, printed verbatim: followed/good → *deserved — repeat*; followed/bad → *bad luck — change nothing*; **deviated/good → DANGEROUS WIN, flagged loudest, standing warning label**; deviated/bad → *lesson — extract the rule, feed The Study*. `gate_verdict[pass]` entries reviewed **on the stated reason only, never on foregone price appreciation**. Aggregates (followed vs overridden %, override hit-rate, alert_ignored ledger) appear only quarterly — no weekly self-benchmarking envy loop.

### F.3 The Study — weekly digest (Naval loop; capped at one screen)

1. **One holding restudied** (rotation, ~each name every 10–15 weeks): thesis excerpt, what changed, one question worth answering.
2. **One mental-model prompt** applied to the current portfolio ("Invert: what would make VEEV worthless in 10 years? Is any of that a missing trigger?") — may propose a trigger addition (tightening is always free).
3. **Journal items approaching review** (preview only; grading is quarterly).
4. **Reading queue** — the restudied holding's most recent report section worth 20 minutes.
5. **Circle note** — one line: did anything this week expand or shrink the circle (owner writes or skips; skipping is fine).
Never contains: performance numbers, post-decision price echoes, new-idea generation (FR14).

---

## G. Outputs

Global rules, enforced structurally: no benchmark/relative performance outside quarterly (absent input, not suppressed section) · no P/L or cost basis in daily/weekly · **no portfolio value in the daily letter (owner decision 2026-07-08; weekly carries it)** · drawdowns on intact theses framed as opportunities against the owner's own anchor · "no action needed" is the headline, not the fine print · staleness always stated · advice, never instructions · calm register, no red-alarm typography for prices, ever.

### G.1 Daily letter (fits one phone screen; never skipped; degrades honestly)

```
Subject: Daily letter — Tue 8 Jul 2026 — ✓ No action needed

Snapshot: manual export of Sun 6 Jul (2 days old) · Prices: fresh (07:00 CET)
Cash 8.1% (band 5–15% ✓) · 11 framework, 1 backfill pending, 2 outside-framework

✓ No triggers fired. All theses intact. Doing nothing is today's best move.
  No-action streak: 34 of the last 40 trading days.

OPPORTUNITIES (intact theses, cheap vs YOUR anchor — this is what you wait for):
• DDOG — 24× P/FCF vs your fair band 28–36× (thesis v2, intact, 4/4 triggers pass):
  ON SALE — ≥20% below your own anchor. Cash available: €11.5k.
  Re-read the thesis first; this is an invitation, not an instruction.

EVENTS: MSFT earnings expected 24 Jul (16 days) — event check will run automatically.
HOUSEKEEPING: AMD still has no thesis (day 12) — backfill via the Gate when you have 30 min.
DATA: all sources fresh.
```
Deliberately absent: portfolio value, P/L, any index, any market recap. Degraded day: *"Checks suspended — prices stale since Thu 3 Jul. Nothing is wrong; I just can't see. Letter resumes full checks when data returns."*

### G.2 Weekly review (deep; Saturday)

1. **Headline verdict** (celebrated if "no action needed"; UNVERIFIABLE escalations surface here).
2. **Portfolio table** — weight, EUR value, framework_status, thesis status + version, conviction, anchor multiple vs band, trigger scorecard (pass/armed/stale). **Total EUR value lives here, weekly.** No P/L column, by design.
3. **Thesis re-validation** — per holding one paragraph + trigger headroom table; backfill and broken-but-held renag lines; anniversary re-affirmations due.
4. **Balance & concentration** — bands per E.3; clusters (local-currency, corr-0.7): membership, weights, **N_eff cluster-basis vs floor 4.0** (+ position-basis as context), correlation matrix; trigger-relaxation echoes (4 weeks).
5. **Outside framework** (FR10) — weight + EUR value + aggregate cap only. No commentary.
6. **Watchlist** — gate-approved: distance to fair-entry and opportunity prices; raw: names + days-to-expiry only.
7. **Prompted questions** — the queued binary trigger questions (stable IDs, D.5).
8. **The Study** (F.3).
9. **Data health appendix** — staleness per source/ticker; suspended checks listed as suspended, not passed.

### G.3 Alert (the only unscheduled output)

```
Subject: Trigger fired — CRWD — T2 (FCF margin) — decision by Tue 14 Jul (7 days)

WHAT YOU COMMITTED TO (thesis v2, committed 2026-03-14, verbatim):
  "T2: FCF margin < 30% for 2 consecutive quarters."
WHAT HAPPENED: Q1 28.4%, Q2 27.1% (yfinance quarterly, fresh, both non-empty).
  Baseline at purchase: 33%.

WHAT THIS IS NOT: not a price alarm. The stock is −9% this month; that is not
why you are reading this and it plays no part in what follows. Cost basis is
not shown and will not be considered.

YOU WROTE (10-year statement, v2): "…the security-platform consolidation trend
runs a decade and the data moat compounds with scale." The question on the
table: does a 2-quarter margin slide invalidate that paragraph?

YOUR OPTIONS (yours alone):
 (a) confirm broken → sell advice for the full position, cost basis ignored
 (b) refute → written evidence required; thesis returns to intact
 (c) revise → only after an explicit refute (goalpost guard)
No response by the deadline → journaled as "alert ignored" (recorded, not judged
today) and escalated in every daily letter. Status meanwhile: under_review.
```
Storm variant: one bundled alert, items ranked by weight, one shared deadline. Type-7 euphoria uses the trim-review variant (thesis intact).

### G.4 Quarterly honesty report (FR13 — the only place a benchmark exists)

1. **The honest question** — "Would an index fund have beaten my process?" Portfolio (EUR) vs **S&P 500 TR (EUR)**: since-inception and trailing-12m lead; the single quarter is shown last and smallest ("do not extrapolate 13 weeks"). Time-weighted, flows excluded (D.4); quantstats stats labeled indicative.
2. **The honest answer** — one written sentence, no hedging. Standing reminder: the 10-year answer is the real one.
3. **Drawdown context** — troughs cross-referenced to the opportunity lines the owner saw at the time.
4. **Process review** — the F.2 batch: 2×2 with entries placed, dangerous wins flagged loudest, passed-winners graded on process, followed/overridden stats, alert_ignored ledger, drift flags, status-buy flags.
5. **Framework audit** — Gate throughput by reason class; trigger relaxations; config changes (journaled diffs).
6. **Records appendix** — cost basis, realized gains, trade-date FX: for the accountant, not for decisions (the one place cost basis is printed).
7. **Verdict + indexing exit clause** — *"If trailing-36m ever shows the index persistently ahead of a clean process, the honest conclusion changes to indexing — that is what this report exists to detect."* Being behind triggers process questions, never "trade more".

### G.5 Archive (NFR4)

Every report: id, type, generated_at, period, data-freshness map, full content — immutable, forever. With thesis versions, the journal, and RunLogs, any past advice is reconstructible exactly as issued.

---

## H. The Scout (idea generation — FR14 formalized)

**Component 7.** Strictly human-triggered; no cadence, no cash-level nudges, no system-initiated prompts (a "you have idle cash, want ideas?" prompt would be action bias built into the pipeline). Scout output is never stored as monitoring state and never appears in any scheduled report. Evidence and verdicts: `docs/research/2026-07-08-longterm-id-frameworks.md`.

### H.1 Universe layer (FinanceDatabase — adopted narrowly)

The circle-of-competence universe is defined **once, as config**, and materialized from the FinanceDatabase equities file — **direct read of `compression/equities.bz2` (pinned commit SHA, cached locally; ~3 lines of pandas), not the pip package** (the package's sole dependency drags in scikit-learn/openpyxl for what is a CSV lookup — NFR7). License MIT (3-0 verified); 160k+ equities keyed by yfinance-compatible tickers with sector/industry/country/market-cap fields; US rows auto-update weekly, EU rows are community-maintained → treated as a starting list, re-verified at screen time.

`universe_config`: countries {US + EU set} · sectors/industries mapped to the circle (software/cloud, healthcare tech & services, AI tooling adjacents) · `exclude_delisted` · market cap ≥ Mid Cap · primary-listing dedup: **US leg via the no-dot filter, EU legs via exchange/market filters** — the library's `only_primary_listing` flag is a "no dot in ticker" heuristic that keeps US cross-listings (ASML) and drops Euronext home listings (ASML.AS); verified live, see research doc open item 3. Universe refresh is a manual ritual (suggested quarterly), journaled as `designation_or_config`.

### H.2 Screen recipes (pre-committed config; human-run per FR14)

Run via TradingView-Screener (human-triggered, results human-read, delayed data), intersected with the H.1 universe. Two named recipes, capped at **top 20 by the cheapness leg**:

- **QV — quality-value (Greenblatt-derived):** cheapness leg (load-bearing): ascending `enterprise_value_ebitda_ttm` (EV/EBIT unavailable in TradingView fields — documented proxy) or `price_free_cash_flow_ttm`; quality cut (confirmatory): `return_on_invested_capital` > 15%; guards: `debt_to_equity` < 1, positive TTM FCF. Cheapness is load-bearing and quality confirmatory because independent evidence shows EBIT/EV carried most of the Magic Formula's alpha.
- **QA — quality-assets (Spitznagel-derived, optional):** `return_on_invested_capital` high + low P/B (Faustmann-ratio proxy).

For hand-shortlisted names only, the candidate dossier computes the **canonical Magic Formula metrics from yfinance statements** (earnings yield = EBIT/EV; return on capital = EBIT/(net working capital + net fixed assets), per the book's definitions — the tiny screener repos' non-canonical math is explicitly not copied).

**Honest evidence note (printed on every screen output):** independent replications put quality-value screening at roughly 3–6%/yr gross outperformance with multi-year losing stretches — not the book's 30%. The screen *surfaces cheap, capital-productive businesses*; it promises nothing. Every candidate still passes the full Gate, and Greenblatt's own investor-behavior data shows second-guessing the screen's valuation call destroys the edge — the Gate judges the framework, not price timing.

### H.3 Candidate flow

Screen results → human eyes → hand-picked tickers enter the watchlist as `raw` (cap 10, 90-day expiry) with `idea_source: scout_screen` → the Gate. Screen output itself is discarded after the session; royalty-trust-style ROIC artifacts are the owner's to sanity-filter.

### H.4 What the Scout is not (evidence-based exclusions)

- **No momentum leg** (QVM-style): momentum pays at 3–12-month rotation horizons and reverses at the 3–5-year horizons this book holds at; a momentum rank sorts beaten-down intact-thesis quality names to the bottom — systematically hiding exactly the "wonderful business on sale" candidates — and is most wrong in post-panic rebounds, the Constitution's prime buying windows. At most, fundamental-momentum may appear as display-only context, never as filter or rank.
- **No ESG factor:** JFE-level evidence is contested (green outperformance as demand artifact, lower expected returns ahead); not in the Constitution; not added.
- **No LLM stock-picking agents:** the "dual memory" citation traced to a paper-mill outlet; the credible line (FinMem/FinAgent/FinCon, arXiv) is day-trading agent research — citable as literature, off-framework as tooling. Its architectural insight *validates the existing design*: the Thesis Register + Decision Journal + Study **is** the long-term episodic memory; LLMs belong in qualitative thesis reasoning, deterministic code in all quantitative math.
- **No FinanceToolkit** (v1): MIT and keyless-capable (verified 3-0), but the Gate needs ~a dozen transparent ratios it already computes from hardened yfinance data, and the mandatory scikit-learn transitive stack fails NFR7 proportionality; its DCF invites assumption-stacking a fair-band system deliberately avoids. **Pre-approved revisit condition:** if Gate ratio needs outgrow ~10 formulas or statement normalization becomes a real maintenance burden, FinanceToolkit in custom-data mode is the verified fallback.
- **No FinQuant, no QuantMuse:** dormant/MVO-category and trading-execution-category respectively — both already-rejected categories.

---

## Traceability — every element earns its place

| Element | Requirement / Constitution rule |
|---|---|
| "No action needed" headline + streak | FR4; Munger action bias |
| Opportunities vs owner's own anchor; invitation framing | FR4; Pillar 1 "buy more on sale"; FR11 |
| No P/L or cost basis in daily/weekly; records appendix quarterly | FR7; Munger sunk cost |
| Benchmark quarantine by absent input; single benchmark S&P 500 TR EUR | FR13; Munger envy; PFIC owner reality |
| Freshness gate; STALE never PASS; UNVERIFIABLE escalation | NFR1, NFR6 |
| Alert quotes trigger + 10-year statement verbatim; WHAT THIS IS NOT | FR2, FR6, FR7, FR8, FR11; commitment device |
| Trigger-loosening guard, drift flags, re-anchoring ritual | Munger commitment bias; NFR4 |
| No autonomous review transitions; no news scanning | Core data-flow principle |
| Hidden concentration: local-currency clusters, N_eff = 1/Σw_c² | FR12 |
| Watchlist zero-automation, cap, expiry; re-pitch confrontation | FR14; Munger FOMO drain |
| Owner-only fields, no defaults, annual re-affirmation | FR9 |
| Status-buy flag + written rebuttal | Naval wealth vs status |
| Process/outcome 2×2; dangerous wins loudest; pass-review on stated reason | FR8; Munger overconfidence; anti-envy |
| Displacement rule at 15; position/cluster caps; leverage tripwire | Pillar 1 concentration; Pillar 2 leverage veto |
| Backfill queue, pause mode, interaction contract, Modified Dietz flows | FR1, FR8, FR13 integrity; NFR5 |
| Scout: human-triggered, pre-committed recipes, capped output, evidence note | FR14; NFR7; Munger honesty |
| RunLog + immutable archive | NFR4 |

## Anti-complexity ledger (deliberately absent)

No news scanning · no price-decline alerts · no automated idea generation · no ML/scoring/ranking of stocks · no portfolio weight optimization · no DCF engine · no EV-denominated anchors (v1) · no momentum · no ESG scoring · no second benchmark · no daily portfolio value or P/L · no letter-grade process scores · no dual review clocks · no automation on raw watchlist items · no intraday anything. Every exclusion is tied to a Constitution failure mode or an NFR7 proportionality test; several carry documented revisit conditions rather than silent finality.

**Parked, unchanged:** technology/runtime; eToro API verification (the E.1 contract makes it a swap-in); SEC EDGAR fallback; TradingView ToS posture (accepted, human-run only; revisit per baseline open item 6).
