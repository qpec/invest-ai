# stock-agentcy — Functional Architecture Elaboration

**Status:** Approved design, **amended 2026-07-08 after the adversarial fidelity review** (`docs/research/2026-07-08-adversarial-fidelity-review.md`): 9 defense-surviving convictions + convergent minor fixes applied — nearly all deletions and clarifications; no new components. Originally synthesized 2026-07-08 from a three-draft / three-judge panel. Owner decisions incorporated: **FR13 benchmark = S&P 500 TR in EUR** · **balance defaults §E.3** · **ETFs outside-framework** · **daily letter carries no portfolio value**.

**Scope:** functional design only; technology/runtime parked. References only adopted tooling: hardened yfinance, pandas+scipy clustering, quantstats (pinned, quarterly-quarantined), TradingView-Screener (human-run), FinanceDatabase universe file (direct read, §H).

**Field notation:** `name : type {allowed values} — source`, where source ∈ **owner** (typed by the owner; never generated — all FR9 fields), **computed**, **fetched** (adopted data stack), **config** (owner-adjustable default; changes journaled).

**Global invariants:**
1. All objects append-only or versioned; nothing destructively edited (NFR4).
2. Every thesis state transition and every owner decision produces a JournalEntry (FR8).
3. No component ever produces an execution instruction — advice only (FR11).
4. Cost basis (`avg_open_price`) exists for record-keeping only; it is a **forbidden input** to any advice computation (FR7).
5. **Price is never a trigger — unconditional.** Price appears in monitoring only as buy-opportunity / fair-entry detection (§E.4). (The former upward "euphoria" trigger was deleted by review F2: the Constitution contains no sell-when-expensive rule; the position hard cap is the only trim advisory, and the weekly review shows the anchor multiple vs band.)
6. Freshness gate: no automated check may FIRE on stale/empty data; stale checks return STALE and are reported as **suspended, never passed** (NFR1, NFR6).
7. Benchmark quarantine is structural: the daily/weekly/event generators have no read path to the benchmark series — not a suppressed section, an absent input (FR13).
8. Privacy (NFR2), functional rule: all stores live in owner-controlled local storage; reports deliver only to the owner's private mailbox; no third-party analytics or telemetry. Implementation detail belongs to the tech phase.

---

## 0. The Loop Spine

The system is four scheduled runs plus three human-triggered runs. Nothing else executes. Every data object exists because a named run reads or writes it.

| Run | Trigger | Reads | Writes | Reaches owner |
|---|---|---|---|---|
| **Daily loop** | once per market day, after US close | Snapshot, PriceCache, Register, config, FX | Daily letter, RunLog | Daily letter (short) |
| **Weekly loop** | **Saturday morning** — deep review happens when nothing can be traded impulsively | Snapshot, PriceCache (1y), FundamentalsCache (refreshed), full Register, Journal open loops, Watchlist, StudyQueue | Weekly review, RunLog, FundamentalsCache, StudyDigest | Weekly review (deep) |
| **Event check** | earnings/filing/mgmt event detected or owner-injected (FR6) | affected thesis + full trigger set, fresh fundamentals for that ticker | Event report or Alert, RunLog | Alert, or one line in next daily letter |
| **Quarterly honesty check** | once per quarter | Snapshot history, PriceCache, BenchmarkSeries (quarantined store), Journal entries at review horizon | Quarterly report, journal reviews, RunLog | Quarterly honesty report |
| **The Gate** (human) | owner submits a candidate | WatchlistItem, FundamentalsCache, Mirror balance pre-check | Thesis (draft), JournalEntry, Watchlist update | Gate verdict document |
| **Scout session** (human, §H) | owner decides to look for ideas | Universe file, screen recipe (config) | WatchlistItem (human-picked only, FR14) | Screen results, human-read, never stored |
| **Owner decision** (human) | alert response, amendment, journal review | Alert, Thesis | Thesis version/status, JournalEntry | Confirmation |

**Data objects:** Snapshot, PriceCache, FundamentalsCache, Thesis, Trigger, Alert, JournalEntry, WatchlistItem, BenchmarkSeries (quarantined), Report archive, and **RunLog** — every run records which inputs it used, the staleness of each, which checks ran, what was decided, and what was emitted. RunLog makes "what did the system know and when" a first-class auditable object (NFR4); journal entries pin `inputs_ref` to the RunLog of the run that informed them.

**FundamentalsCache is an append-only per-ticker archive keyed by period-end date** (review MA-1): each weekly/event refresh appends newly observed periods and never overwrites. This serves invariant 1, revision pinning (B.3), and — decisively — trigger persistence windows: yfinance returns only ~4–5 statement periods per fetch, so multi-quarter checks become evaluable as the archive accumulates history.

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
| `owner_earnings` | `fcf_ttm` — computed, **pinned construction**: Σ last 4 quarterly (Operating Cash Flow − \|Capital Expenditure\|); any empty period → STALE, never a partial sum (MA-11) · `sbc_ttm` — same statement, same summation · **`owner_fcf_ttm = fcf_ttm − sbc_ttm`** (BUF-5: stock-based compensation is a real cost of maintaining competitive position — decisive for a SaaS-heavy circle where SBC runs 10–30% of FCF) · `owner_fcf_per_share_ttm` — computed (`get_shares_full` resampled) · `owner_fcf_margin_ttm` — computed · `narrative` — owner. Raw FCF printed alongside for transparency; **all anchor denominators use owner_fcf**. | mixed |
| `valuation_anchor` | `metric`: **P_FCF on owner-FCF — v1's only anchor** (BUF-1: P_E re-admits reported EPS, the metric the Constitution verbatim excludes, into the fair-band machinery; P_S ignores cash generation; EV-metrics need net-debt machinery that costs more than it adds. Revisit only if a thesis genuinely cannot be anchored on FCF per share.) · `value_at_purchase` — computed at activation; **null for `origin = backfill`** (the purchase-date multiple is unreconstructable and unused — the fair band is the only live anchor, BUF-12) · `fair_band_low/high` (multiple range) — owner · **`fair_band_mid = (fair_band_low + fair_band_high) / 2`** — computed (MA-9) · `denominator_note` — owner | mixed |
| `conviction` | {high, medium, low} — drives the sizing advice table in E.3 (BUF-3); the label itself is never system-set or system-capped | **owner — never generated (FR9)** |
| `mgmt_trust` | {trusted_owner_operator, trusted_professional, neutral, distrust} + note. `distrust` at the Gate = Hell-No HN3 fail; **post-activation the owner may downgrade to `distrust` at any time** — doing so auto-opens an owner-initiated review (A.2). Trust is an ongoing condition, not a purchase-time checkbox. | **owner (FR9)** |
| `circle_fit` | {core, edge} + note (which competence domain) | **owner (FR9)** |
| `time_horizon` | **`10y_plus` only.** Anything shorter is, per the Constitution, speculation — the Gate rejects it. | owner |
| `ten_year_statement` | text, first person: "would I hold if the market closed for a decade, and why" | **owner** |
| `triggers` | list<Trigger> (§B), **min 2, max 5** — fewer is unfalsifiable, more is noise. **At least one committed trigger must carry a `moat_link`** (a type-2 pricing-power proxy or a type-5 owner-attested question such as "NRR < 110%?") so the moat claim — the most load-bearing Buffett claim — can never go permanently unfalsified (BUF-4). | owner-committed, system-assisted drafting |
| `status_buy_flag` | bool + note — set by exactly one input: the owner's hesitant or negative answer to the status question in C.5 (the former +100%-in-12-months price heuristic was deleted — it flagged precisely the compounders the framework exists to buy, F11) | owner-derived |

**Rules:** `conviction`, `mgmt_trust`, `circle_fit`, `ten_year_statement` have no defaults and cannot be copied from a prior thesis. The system asks; the owner answers; blank blocks activation. **Annual re-affirmation (judgment anti-staleness):** at each thesis anniversary the weekly review asks the owner to re-affirm conviction, mgmt_trust and circle_fit (one prompted question); unresolved skips surface via the standard escalation (B.3). Fundamentals get weekly refresh — judgment gets at least yearly refresh.

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
- **Trigger-loosening guard:** loosening (weaker threshold, longer persistence, deletion) is allowed only while `status = intact` — never during `under_review` (you may not move the goalposts while the ball is in the air; during review, `revise` is possible only after an explicit `refute`). Every relaxation prints in the weekly review for 4 weeks, **stating the headroom at loosening time** ("loosened T4 from 2% to 3% while dilution stood at 2.7%") — the echo carries the incriminating fact itself; no separate drift-flag mechanism (review F4-S). Tightening and adding triggers are always free.
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
owner_earnings: fcf_ttm ≈ $1.1B · sbc_ttm ≈ $0.45B · owner_fcf ≈ $0.65B ·
  owner_fcf/share ≈ $4.0 · "subscription cash up front, negligible capex,
  net cash — but SBC is a real cost; owner earnings, not reported FCF."
valuation_anchor: P_FCF (owner-FCF) · at purchase 30.0 · fair band 25.0–35.0
conviction: high   mgmt_trust: trusted_owner_operator (founder-CEO, large stake)
circle_fit: core (healthcare SaaS)   time_horizon: 10y_plus
ten_year_statement: "Yes. Life-sciences regulation only accumulates; the vendor
  that owns the validated record layer compounds with the industry."
triggers: T1 growth_floor rev YoY <10% (2q) · T2 margin_erosion owner-FCF margin
  <20% [moat_link: switching_costs] · T3 owner_attested: founder-CEO departs
  · T4 dilution shares +3%/12m
v2: T4 2%→3% ("SBC settle-cadence noise", journaled JE-0007; headroom at
  loosening: dilution stood at 1.9% vs new 3% threshold)
```

---

## B. Trigger taxonomy

### B.1 Trigger schema

`trigger_id` — computed · `type` (B.2) — owner · `statement` : one falsifiable sentence, owner's words ("If X, the reason I own this is gone") — **owner** · `metric` + `comparator` + `threshold` — owner · `moat_link` : moat_type or null (A.1 rule: ≥1 trigger per thesis carries one) — owner · `persistence` {single_observation, 2_consecutive_quarters, ttm} — owner, default per type · `check_method` {automated, prompted} — computed from type (**testable ≠ automatable; it means falsifiable, pre-committed, and actually checked**) · `data_source` {yf_quarterly_statements, yf_shares_full, yf_officers, yf_calendar, owner_attestation} — computed · `cadence` {weekly, event} — computed · `status` {armed, fired, stale, retired} · `last_checked`, `last_result` {PASS, FIRE, STALE, BOOTSTRAPPING, UNVERIFIABLE} · `fired_at`, `resolution` {confirmed_broken, refuted, revised}.

All automated checks run through the hardened yfinance layer: cached + paced, **emptiness detection on every field** (empty → STALE, never PASS/FIRE), shares via `get_shares_full` resampled + dedup'd (NFR6).

### B.2 The five trigger types

| # | Type | Testable form | Source | Cadence | Check |
|---|---|---|---|---|---|
| 1 | `growth_floor` | revenue (or committed line) YoY < X% · default 2 consecutive quarters | statements archive | weekly + event | automated |
| 2 | `margin_erosion` | owner-FCF margin TTM < X% or gross margin TTM < X% (owner picks the line that proxies the moat's pricing power — automatable moat proxies live here) | statements archive | weekly + event | automated |
| 3 | `balance_sheet_safety` | net debt / EBITDA > X, or cash < X quarters of burn. **Pinned rows (MA-2):** net debt = `Total Debt` − `Cash And Cash Equivalents`; EBITDA from the named income-statement row; **any absent row → STALE, never a silent zero.** | statements archive | weekly + event | automated |
| 4 | `dilution` | shares outstanding trailing-12m growth > X% (default 3%) | shares_full | weekly | automated |
| 5 | `owner_attested_event` | pre-committed **binary question** put to the owner (at each earnings event; weekly if flagged urgent): non-automatable moat proxies ("NRR < 110%?"), management/trust events (named person departs; restatement; related-party dealing), thesis-specific events ("loses exclusivity on X"). **Dated milestones ride this type** with the date in the committed statement ("after the earnings on/after 2027-03-01: is ARR ≥ €500m?") — no separate trigger type or cadence (F7). The weekly `companyOfficers` diff is a tripwire that queues the question — **a tripwire, not truth**, and per MA-6 an *unverified* one: neither research doc audits `companyOfficers`; a one-time verification against actual portfolio tickers is required before its silence may be trusted; best-effort until then. The owner is the sensor; the system is the scheduler and record-keeper. | owner_attestation (+officer-diff tripwire) | event / weekly | prompted |

**Bootstrap rule (MA-1):** when a trigger's persistence window needs more history than the FundamentalsCache archive yet holds (e.g. "2 consecutive quarters YoY" needs 6 quarters; a cold fetch returns 4–5), the trigger reports **BOOTSTRAPPING** — a STALE variant that can never FIRE or PASS — together with the date it becomes evaluable. The Gate dossier and weekly review print the same honestly.

**Restated, now unconditional (F2):** there is no price trigger of any kind — no decline trigger, no euphoria trigger. A drawdown with an intact thesis routes to the buy-opportunity check (E.4); expensiveness is visible weekly (anchor multiple vs band, G.2); the position hard cap (E.3) is the only trim advisory.

### B.3 Firing, escalation, storms, revisions

1. FIRE → `thesis: intact → under_review` (same instant), `review_deadline = +7d`; Alert per G.3.
2. Owner options (each journaled): `confirm_broken` → sell advice without cost basis; `refute` → written evidence, back to intact; `revise` → only after refute (goalpost guard A.3).
3. No decision by deadline → `alert_ignored` auto-journaled; heads every daily letter until resolved.
4. **UNVERIFIABLE is never OK:** a prompted question skipped twice, or an automated check stale, reports UNVERIFIABLE/STALE in every review; **3 consecutive unverifiable weeks escalate to the weekly headline.** Suspended ≠ green.
5. **Alert storms (correlated stress):** multiple fires on one day → a single bundled alert, items ranked by position weight, one shared deadline. A market-wide drawdown across intact theses is, by construction, an *opportunities* section — the calmest week the system has.
6. **Data revisions:** every verdict is pinned to data-as-fetched (`RunLog.inputs_ref`) in the append-only archive; revisions never retro-fire or retro-clear a verdict, and armed triggers simply evaluate current data at their next check. Past-verdict audits are reconstructible on demand from the archive — there is no automated counterfactual replay (F9: NFR4 is fully satisfied by pinning; scheduled re-evaluation of history is machinery without a decision attached).

---

## C. The Gate

Nothing reaches the portfolio without passing every step in order: cheap human filters before expensive analysis (Munger before Buffett), owner judgment before drafting, drafting before verdict.

### C.1 Watchlist (entry — FR14)

`WatchlistItem`: `ticker` — owner · `added_at` — computed · `idea_source` {own_research, scout_screen, reading, referral} — owner · `one_line_why` — owner · `stage` {raw, gate_approved_waiting} — computed. **Cap 10 raw items · 90-day expiry** (expiry logged in the RunLog, not journaled — an expired idea the owner already ignored for 90 days is not a decision; ideas must earn a Gate run or die quietly).
- Entry is human-triggered only (FR14). Tooling-assisted path = the Scout (§H): human-run screens, human-read results, hand-picked tickers.
- `raw` items get **zero automation** — no prices, no monitoring, no "your watchlist moved" notes.
- `gate_approved_waiting` items carry an activated draft thesis and exactly **one** armed daily check: fair-entry (C.6/E.4).
- **Re-pitch confrontation:** re-adding a previously rejected ticker surfaces the original `gate_verdict` journal entry verbatim before the Gate will run again.

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

Rejections stay visible: the quarterly review reads `gate_verdict[pass]` entries **on the stated reason only, never on foregone price appreciation** — a process-correct rejection that later "missed a winner" is graded GOOD PROCESS (the fee for never taking the catastrophic loss).

### C.4 Step 3 — Buffett dossier (system)

Assembled from the hardened data layer, every number freshness-stamped, empty statements declared: (1) moat-evidence candidates — margins & trend over **all available reported periods** (typically 4 annual + 4–5 quarterly at first fetch, growing with the archive; the dossier prints the period count and dates it rests on — MA-5); (2) owner-earnings picture — owner-FCF (= FCF − SBC per A.1), per-share on resampled shares, SBC & dilution trend, net cash/debt; (3) valuation-anchor material — P_FCF on owner-FCF: current + available-period range; the dossier proposes history, **the owner sets the band**; (4) 10-year framing questions. Missing/empty fundamentals → the Gate **pauses**; no verdict on absent owner-earnings data.

### C.5 Step 4 — Owner judgment (FR9, sacred)

The system asks; only the owner answers; no defaults, no suggestions: `conviction` · `mgmt_trust` + note · `circle_fit` confirmation · `ten_year_statement` · the status question verbatim: *"Would you still buy this if you could never tell anyone you owned it?"* A hesitant or negative answer sets `status_buy_flag = true` — the owner's answer is the flag's only source (F11). **The system never constrains conviction** — sizing consequences live in E.3, labels stay the owner's.

### C.6 Step 5 — Thesis drafting → verdict

Thesis per A.1 (system fills fetched/computed fields; owner writes owner fields and commits 2–5 triggers incl. one moat-linked; system may propose trigger *templates*, thresholds are owner-set).

| Verdict | Meaning | Consequence |
|---|---|---|
| `BUY_READY` | framework-clean, price inside or below fair band | advice text incl. **suggested max initial weight from E.3's conviction-tiered table (BUF-3)**; for `conviction = low` or `circle_fit = edge`, the verdict prints the standing question: *"the mandate is 10–15 **high-conviction** positions — why does this belong in a concentrated book?"* If `status_buy_flag` is set, BUY_READY requires the owner's written rebuttal first (friction by design). Owner executes or not; thesis activates when the position appears in a Snapshot. Non-execution after 30 days → prompt: journal `advice_rejected` or move to WATCH. |
| `WATCH` | business passes, price above fair band | thesis stays `draft`; **one** armed daily check: **fair-entry** (price ≤ `fair_band_high` × denominator — Buffett's wonderful-business-at-fair-price line, made literal). The ≥20%-discount opportunity check applies to *held* positions only — two thresholds for the same unowned stock was one ping too many (F12/FS-F7). |
| `PASS` | rejected at any step | journaled with step + reason class {outside_circle, hell_no_HN1..HN5, no_moat_evidence, owner_earnings_absent, owner_declined}. |

**Approval expiry:** BUY_READY/WATCH lapse after **12 months** — a stale thesis is not a thesis; re-approach = fresh Gate run. **Displacement rule:** at 15 framework positions, a BUY_READY verdict must name which existing holding this candidate beats, and why (Munger opportunity cost made mechanical).

**Backfill Gate (FR1):** existing holdings without a thesis run the **full Gate, Steps 1–5 including the Buffett dossier**, with two differences: no price verdict (the position is already held; `value_at_purchase` stays null, BUF-12) and outcomes {`activate_backfill`, `no_thesis_exists`}. `no_thesis_exists` = the honest admission there is no thesis → treated as broken → sell advice (cost basis ignored). **Bootstrap sequencing:** backfill queue ordered by position weight, largest first; suggested pace one Gate per week; until backfilled a holding is monitored for balance only. **While the owner is on-pace with the suggested queue, the reminder appears weekly (G.2) only — the daily letter does not nag a plan being followed** (NAV-7).

---

## D. The Watchdog

Reads only the Thesis Register and config. Never scans open-ended news. Four cadences + interaction contract + pause mode.

### D.1 Daily loop

- **Inputs:** latest Snapshot (any age — NFR1); daily closes for held + gate-approved tickers + FX pairs; Register; config; weekly-computed denominators.
- **Checks:** (1) buy-opportunity scan on held intact theses + fair-entry scan on WATCH items (E.4); (2) balance drift vs bands (E.3), last snapshot marked-to-market; (3) unresolved items (open reviews past deadline, alert_ignored, broken-but-held); (4) data health (snapshot age, per-ticker price staleness); (5) earnings within 21 days → information-only preview line, labeled "expected" (MA-7).
- **Outputs:** daily letter (G.1). Default and celebrated: **"No action needed"** (FR4).
- **Degradation:** stale snapshot → banner "positions as of {date}"; per-ticker stale price → opportunity/fair-entry lines suppressed for that ticker with an explicit note — **never computed on stale, empty-quarter, or non-positive denominators; suppression is stated, silence never means "no opportunity"** (MA-3); **>50% tickers stale → "market data degraded"**, checks 1–2 suspended and say so; total failure → the letter still sends: "Data sources unavailable since {t}; last known state; no checks performed. Nothing is wrong; I just can't see."

### D.2 Weekly loop (Saturday, FR5)

- **Inputs:** daily inputs + quarterly statements per holding (emptiness-checked, appended to the archive), `get_shares_full` refresh, `companyOfficers` diff (best-effort, B.2), 252-day return history (all mappable invested positions), earnings calendar.
- **Checks:** (1) fundamentals refresh → recompute owner-FCF TTM/margins/dilution; refresh `opportunity_price` and `fair_entry_price` denominators; (2) full re-test of every armed automated trigger + queue prompted questions; (3) thesis re-validation per holding: status, **trigger headroom table** ("growth 14.2% vs floor 10% — headroom 4.2 pts"), anchor multiple vs band; (4) balance review per E.3 + **hidden-concentration (FR12) per E.5** + **dividend receipts since last snapshot per holding, with the standing note when dividend cash idles above the band floor: "Constitution default: reinvest unless income is needed" (BUF-2)**; (5) officer-diff tripwire → queued question; (6) FR1 sweep → backfill queue status; (7) anniversary re-affirmations due (A.1); (8) Study digest (F.3).
- **Outputs:** weekly review (G.2); prompted-question queue; alerts for fires.
- **Degradation:** empty statements → holding's fundamental triggers STALE, printed as "suspended, not passed"; <120 days return history → own cluster + flag; clustering failure → last week's clusters, tagged stale.

### D.3 Event checks (FR6)

- **Sources:** (a) **statement-fingerprint change detected in the weekly refresh — the authoritative earnings detector**; the yfinance calendar is a best-effort *preview* whose forward dates are always labeled "expected" (MA-7: calendar reliability is unverified); late detections marked "detected late" for audit; (b) owner ad-hoc event entry — the owner is a first-class sensor; (c) officer-diff escalation (best-effort, B.2). **Filings honesty (FR6):** filings detection is owner-attested — the owner is the filings sensor — until the deferred SEC EDGAR fallback is adopted; the design claims no automated filings feed it does not have.
- **Checks:** immediate, single-holding: fresh statements (bypass cache, still paced, appended to archive); all armed triggers for that thesis; all prompted questions queued with the event named.
- **Outputs:** event report (archived); quiet outcome = one line in the next daily letter ("{TICKER} earnings checked; {n}/{n} triggers pass; no action needed") — no extra ping. Fires → Alert.
- **Degradation:** post-earnings data lag → retry daily for 7 days; prompted questions to the owner don't wait for the data.

### D.4 Quarterly honesty check (FR13, quarantined)

- **Inputs:** snapshot history (with dated external flows, E.1), adjusted price history, FX history, benchmark series (`^SP500TR` × USD→EUR — the quarantined store), quantstats pinned.
- **Method:** daily portfolio EUR return series reconstructed from snapshots × adjusted closes × FX; external flows handled time-weighted (Modified Dietz per inter-snapshot period, geometrically linked) so deposits never masquerade as alpha; inception = first snapshot date. **Flow capture is reconciliation-driven, not ritual:** the owner is prompted for flow confirmation only when E.1 reconciliation finds an unexplained cash/quantity delta (MA-12); quarters whose net external flows exceed ~5% of portfolio value are additionally labeled "approximate — large flows this period." Dividends: adjusted closes embed them in returns; dividend cash arriving in snapshots is an internal flow. Non-mappable positions (MA-4) are excluded from the return series with their weight printed. Stats: CAGR, max drawdown, volatility, Sharpe/Sortino + `qs.reports.metrics` vs benchmark, both series in EUR, labeled **indicative, not authoritative**.
- **Outputs:** quarterly honesty report (G.4) + the journal review batch (F.2).
- **Degradation:** quantstats breakage → **four hand-computed stats** (period return, vs-benchmark simple return, max drawdown, volatility) — the honesty question still gets answered. Snapshot gaps >7d → periods marked approximate; >30d → relative-performance headline withheld ("better silent than wrong").

### D.5 Owner interaction contract

Every owner-facing ask is a first-class object: stable ID, enumerated reply options, free-text where committed. Prompted trigger questions accept exactly {yes, no, can't-verify + note}; alerts accept exactly the three options of B.3; Gate/journal fields accept their schema. Malformed or partial replies → one re-prompt, then counted unanswered. Unanswered pre-fire prompts follow the UNVERIFIABLE escalation (B.3.4); unanswered alerts follow the `alert_ignored` path. Every answer is journaled with its ask-ID. This contract is the system's most-used interface and is deliberately boring: binary where possible, pre-committed everywhere.

### D.6 Pause mode (owner absence)

Owner declares an absence window (journaled on/off). During it: **all deadline and skip counters freeze** — alert decision windows, prompted-question skip counts, re-affirmation skips, UNVERIFIABLE week counts (NAV-6) — alerts still deliver, weekly reviews continue. Daily letters follow `daily_letter_mode` config {**always** (default — FR4 posture: the letter is never skipped), quiet (during declared absence: checks still run and log to RunLog every day; letters suppressed except alerts)} (NAV-9). A vacation must not pollute the FR8 process record with fake "ignored" decisions.

---

## E. Portfolio Mirror

### E.1 Source-agnostic snapshot ingestion

`Snapshot`: `snapshot_id`, `as_of`, `source` {api_pull, manual_export, manual_entry}, `positions`, `cash_balance`, `external_flows`: list of {date, amount, direction} since the previous snapshot — **populated by reconciliation, owner-confirmed only when a cash/quantity delta is unexplained** (MA-12; feeds D.4).

**Canonical contract** — any adapter (future eToro API, CSV export parser, manual form) produces identical per-position fields; the rest of the system cannot tell sources apart: `symbol` (mapped to yfinance ticker via owner-maintained `symbol_map`) · `instrument_type` {stock, etf, crypto, copyportfolio, cash} · `quantity` · `avg_open_price` (**record-keeping only, forbidden in advice — FR7**) · `native_currency` · `market_value_native` · `market_value_eur` (FX pairs derived from the native currencies present: `{CUR}EUR=X` daily closes, cached; same source converts the benchmark) · `weight` · `framework_status` (E.2) · `thesis_id` · `leverage` / CFD metadata.

**Leverage tripwire:** any position with leverage > 1 or `instrument_type` CFD fires an immediate Hell-No violation alert — the Constitution's leverage veto enforced continuously, not just at the Gate.

**Non-mappable instruments (MA-4):** positions without a yfinance-mappable symbol (copyportfolios, some crypto) are valued at last-snapshot value between snapshots; they are **excluded from clustering and return series**, and both the FR12 section and the quarterly report print the excluded weight explicitly ("X% of the book is unpriced between snapshots") — never silently treated as priced.

**Operating contract (manual mode):** expected export cadence weekly before the Saturday run + after any trade. Staleness ladder: prices >3 trading days → automated checks suspended (honest wording); snapshot >14 days → weights marked stale; >30 days → balance advisory suspended + fresh export requested. The daily letter itself is never skipped (subject to `daily_letter_mode`, D.6).

**Reconciliation on every snapshot:** new ticker without thesis → `backfill_pending` (crypto/copyportfolio/ETF → prompt owner once to designate `outside_framework`); disappeared ticker → prompt to journal the close; quantity change → journal prompt (add/trim); unexplained cash delta → flow-confirmation prompt (MA-12). Closes the FR8 loop for trades executed off-system.

### E.2 Framework vs outside-framework (FR10)

- `framework`: active thesis; fully monitored.
- `backfill_pending`: equity without thesis — flagged weekly until the backfill Gate (C.6) resolves it.
- `outside_framework`: crypto, copyportfolios, **and ETFs by default (owner decision 2026-07-08)** — visible in all balance views, **included in concentration math where a return series exists (E.5), excluded** from thesis monitoring, triggers, and buy-opportunity logic. No thesis pretension. Revisit the ETF default only if a thesis-worthy ETF need actually emerges.

### E.3 Balance model — defaults approved 2026-07-08, pruned by review (all config; changes journaled)

| Parameter | Default | Behavior when breached |
|---|---|---|
| `cash_band` | 5–15% | below: "buying power thin"; above: "cash idle — no forced deployment" (never "you must invest") |
| `max_position_soft` / `hard` | 15% / 20% | soft: "winner has run — review, no obligation"; hard: trim-review advice. Winners run; the hard cap is the survival line — **and the only trim advisory in the system** (F2). |
| `max_cluster_weight` | 40% of invested (ex-cash) | "cluster {label} is {w}% — are these separate bets?" |
| `min_effective_bets` (FR12) | **N_eff ≥ 4.0, cluster-weight basis (1/Σw_c²)** — the single concentration floor | "your {n} positions are behaving like {N_eff} bets" |
| `position_count_band` | 10–15 framework | below band-low (10): "concentration beyond mandate — deliberate?" (the former shadow constant <8 is deleted, BUF-11); >15: "diworsification" + displacement rule active (C.6) |
| `outside_framework_cap` | 10% | weekly advisory flag (FR10: visible, not forbidden) |
| `buy_opportunity_discount` | 20% | E.4 |
| `alert_decision_days` | 7 | B.3 |
| `initial_weight_by_conviction` (BUF-3) | high ≤10% · medium ≤6% · low ≤3% of portfolio, initial sizing advice at BUY_READY | printed in the Gate verdict; drift thereafter governed by the position caps. The conviction *label* stays owner-only (FR9) — the system derives sizing advice from it, never the reverse. |

Deleted by review: `max_sector_weight` (a knob the design itself declared non-binding — the cluster check is the safeguard; sector labels lie, correlations don't; the yfinance sector label remains as a display column in the weekly table, F8/FS-F6) and the position-basis N_eff floor (two floors where FR12 needs one).

### E.4 Buy-opportunity & fair-entry checks

Weekly, per thesis: `opportunity_price = (1 − discount) × fair_band_mid × denominator_per_share` and `fair_entry_price = fair_band_high × denominator_per_share`, where the denominator is owner-FCF per share (A.1), refreshed weekly — the anchor is a **multiple**, the denominator refreshes itself, so thresholds never rot as fundamentals grow. **Denominators carry the freshness stamp of the statements they were computed from; a stale, empty-quarter, or non-positive denominator suspends that ticker's checks with an explicit "suspended" note — silence never means "no opportunity" (MA-3).**

Daily, cheap comparisons — each check arms exactly one audience (F12): **fair-entry fires for WATCH items** (*"{TICKER} has entered your fair band ({multiple}× vs {low}–{high}×). Wonderful business, fair price — the Gate approved it; the price now agrees."*) and **opportunity fires for held intact theses** (*"{TICKER} trades at {multiple}× vs your band {low}–{high}× — a ≥20% discount to your own anchor. Thesis intact ({n}/{n} triggers pass). Great businesses on sale is the plan working."*). Cash-band status alongside; invitation framing; no urgency language, ever.

### E.5 Hidden-concentration method (FR12)

Daily returns **in local currency** (a common EUR/USD factor must not fuse all USD holdings into one fake cluster), 252-day lookback, ≥120 overlapping days (else own cluster + flag). Distance `sqrt((1−corr)/2)`, average linkage, `fcluster(criterion="distance", t=sqrt((1−0.7)/2)≈0.387)` — positions cluster when average correlation exceeds 0.7 (config). `N_eff = 1/Σw_c²` over cluster weights (invested, ex-cash, incl. outside-framework positions **that have a return series; non-mappable positions are excluded and their weight printed** — MA-4). Weekly review: cluster membership table, cluster weights, N_eff, correlation matrix. Zero new dependencies.

### E.6 FR13 benchmark (approved 2026-07-08)

**S&P 500 Total Return, measured in EUR** (`^SP500TR` × daily USDEUR; portfolio series likewise EUR). Rationale: (1) **PFIC reality** — under the owner's tax residency, UCITS trackers are punitively taxed; the realistic passive counterfactual is a US-domiciled fund; (2) opportunity-set match — the book is predominantly USD US large-cap; (3) EUR on both sides keeps FX out of the process comparison. Documented alternative: VT (US-domiciled total-world) in EUR. One benchmark only; config change requires a journaled reason.

---

## F. Decision Journal + The Study

### F.1 JournalEntry schema

`entry_id` (append-only, immutable) · `timestamp` · `decision_type` {buy, add_to_position, trim, sell, hold_after_review, advice_rejected, alert_ignored, gate_verdict [pass/watch/buy_ready], trigger_resolution [confirmed_broken/refuted/revised], thesis_revision, config_or_designation [config_change/outside_framework]} — eleven types with subtypes (watchlist expiry moved to the RunLog: not a decision) · `ticker`/`thesis_ref` (`thesis_id@version`) · `system_recommendation` (verbatim at that moment) · `owner_action` {followed, overridden, no_action} · `reasoning_at_the_moment` — **owner, mandatory for owner-initiated types; captured before the outcome is known; one prose field** (absorbs the former separate decision statement, F5) · **`expectation_and_falsifier`** — "what I expect, and what would prove me wrong" in one field; **for buy/add decisions this defaults to the committed trigger set (a `thesis_id@version` reference — the thesis IS the falsifier), no new prose; free text required only for overrides and deviations, where the thesis does not capture the bet** (F5/FS-F5) · `review_horizon` (default 1y; `too_early` re-queues one horizon) · `inputs_ref` (RunLog pin: exactly which data this decision saw) · `process` {followed, deviated} + **mandatory note when deviated** (binary — honest, gradeable immediately) · `outcome_grade` {good, neutral, bad, too_early} + note — filled **only at review**, judged against the expectation/falsifier and thesis validity, never raw price · `emotional_note` (optional — Munger's cheapest overconfidence detector).

Auto-created entries: `alert_ignored` and `gate_verdict[pass]` (every rejection is a decision).

### F.2 Process-vs-outcome review

Batched into the quarterly report (one honest hour per quarter). The 2×2, printed verbatim: followed/good → *deserved — repeat*; followed/bad → *bad luck — change nothing*; **deviated/good → DANGEROUS WIN, flagged loudest, standing warning label**; deviated/bad → *lesson — extract the rule, feed The Study*. `gate_verdict[pass]` entries reviewed **on the stated reason only, never on foregone price appreciation**. Aggregates (followed vs overridden %, override hit-rate, alert_ignored ledger, **the quarter's no-action ratio** — moved here from the daily letter, NAV-8) appear only quarterly — no weekly self-benchmarking envy loop.

### F.3 The Study — weekly digest (Naval loop; capped at one screen)

1. **One holding restudied** (rotation, ~each name every 10–15 weeks): thesis excerpt, what changed, one question worth answering.
2. **One mental-model prompt** applied to the current portfolio ("Invert: what would make VEEV worthless in 10 years? Is any of that a missing trigger?") — may propose a trigger addition (tightening is always free).
3. **Journal items approaching review** (preview only; grading is quarterly).
4. **Reading queue** — the restudied holding's most recent report section worth 20 minutes.
5. **Circle note** — one line: did anything this week expand or shrink the circle (owner writes or skips; skipping is fine).
Never contains: performance numbers, post-decision price echoes, new-idea generation (FR14).

---

## G. Outputs

Global rules, enforced structurally: no benchmark/relative performance outside quarterly (absent input, not suppressed section) · no P/L or cost basis in daily/weekly · **no portfolio value in the daily letter** (owner decision 2026-07-08; weekly carries it) — **cash appears daily as band-percentage only, never in euros** (FS-F8) · drawdowns on intact theses framed as opportunities against the owner's own anchor · "no action needed" is the headline, not the fine print · staleness always stated · advice, never instructions · calm register, no red-alarm typography for prices, ever · privacy per invariant 8.

### G.1 Daily letter (fits one phone screen; never skipped; degrades honestly)

```
Subject: Daily letter — Tue 8 Jul 2026 — ✓ No action needed

Snapshot: manual export of Sun 6 Jul (2 days old) · Prices: fresh (07:00 CET)
Cash 8.1% (band 5–15% ✓) · 11 framework, 1 backfill pending, 2 outside-framework

✓ No triggers fired. All theses intact. Doing nothing is today's best move.

OPPORTUNITIES (held intact theses, cheap vs YOUR anchor — this is what you wait for):
• DDOG — 24× P/FCF vs your fair band 28–36× (thesis v2, intact, 4/4 triggers pass):
  ON SALE — ≥20% below your own anchor. Cash band ✓ (8.1%).
  Re-read the thesis first; this is an invitation, not an instruction.

EVENTS: MSFT earnings expected 24 Jul (16 days, calendar estimate) — event check
  will run automatically on detection.
DATA: all sources fresh.
```
Deliberately absent: portfolio value, P/L, euro amounts, any index, any market recap, streak gamification (the no-action *ratio* appears quarterly in the process review — a streak counter is a status game against oneself, NAV-8). Degraded day: *"Checks suspended — prices stale since Thu 3 Jul. Nothing is wrong; I just can't see. Letter resumes full checks when data returns."*

### G.2 Weekly review (deep; Saturday)

1. **Headline verdict** (celebrated if "no action needed"; UNVERIFIABLE escalations surface here).
2. **Portfolio table** — weight, EUR value, framework_status, thesis status + version, conviction, sector label (display only), anchor multiple vs band, trigger scorecard (pass/armed/stale/bootstrapping). **Total EUR value lives here, weekly.** No P/L column, by design.
3. **Thesis re-validation** — per holding one paragraph + trigger headroom table; backfill queue status (next in queue; daily nag suppressed while on-pace, NAV-7); broken-but-held renag lines; anniversary re-affirmations due.
4. **Balance & concentration** — bands per E.3; clusters (local-currency, corr-0.7): membership, weights, **N_eff vs floor 4.0**, correlation matrix, unpriced-weight line (MA-4); **dividends received since last snapshot per holding + reinvestment reminder when idle (BUF-2)**; trigger-relaxation echoes with headroom-at-loosening (4 weeks, A.3).
5. **Outside framework** (FR10) — weight + EUR value + aggregate cap only. No commentary.
6. **Watchlist** — gate-approved: distance to fair-entry price; raw: names + days-to-expiry only.
7. **Prompted questions** — the queued binary trigger questions (stable IDs, D.5).
8. **The Study** (F.3).
9. **Data health appendix** — staleness per source/ticker; suspended checks listed as suspended, not passed.

### G.3 Alert (the only unscheduled output)

```
Subject: Trigger fired — CRWD — T2 (owner-FCF margin) — decision by Tue 14 Jul (7 days)

WHAT YOU COMMITTED TO (thesis v2, committed 2026-03-14, verbatim):
  "T2: owner-FCF margin < 20% for 2 consecutive quarters."
WHAT HAPPENED: Q1 18.4%, Q2 17.1% (statements archive, fresh, both non-empty).
  Baseline at purchase: 23%.

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
Storm variant: one bundled alert, items ranked by weight, one shared deadline.

### G.4 Quarterly honesty report (FR13 — the only place a benchmark exists)

1. **The honest question** — "Would an index fund have beaten my process?" Portfolio (EUR) vs **S&P 500 TR (EUR)**: since-inception and trailing-12m lead; the single quarter is shown last and smallest ("do not extrapolate 13 weeks"). Time-weighted per D.4; flow-approximation and unpriced-weight caveats printed; quantstats stats labeled indicative.
2. **The honest answer** — one written sentence, no hedging. Standing reminder: the 10-year answer is the real one.
3. **Drawdown context** — troughs cross-referenced to the opportunity lines the owner saw at the time.
4. **Process review** — the F.2 batch: 2×2 with entries placed, dangerous wins flagged loudest, passed-winners graded on process, followed/overridden stats, alert_ignored ledger, no-action ratio.
5. **Framework audit** — Gate throughput by reason class; trigger relaxations with headroom; config changes (journaled diffs).
6. **Records appendix** — cost basis, realized gains, trade-date FX: for the accountant, not for decisions (the one place cost basis is printed).
7. **Verdict + indexing exit clause** — *"If trailing-36m ever shows the index persistently ahead of a clean process, the honest conclusion changes to indexing — that is what this report exists to detect."* Being behind triggers process questions, never "trade more".

### G.5 Archive (NFR4)

Every report: id, type, generated_at, period, data-freshness map, full content — immutable, forever. With thesis versions, the journal, and RunLogs, any past advice is reconstructible exactly as issued.

---

## H. The Scout (idea generation — FR14 formalized)

**Component 7.** Strictly human-triggered; no cadence, no cash-level nudges, no system-initiated prompts. Scout output is never stored as monitoring state and never appears in any scheduled report. Evidence and verdicts: `docs/research/2026-07-08-longterm-id-frameworks.md`.

### H.1 Universe layer (FinanceDatabase — adopted narrowly)

The circle-of-competence universe is defined **once, as config**, and materialized from the FinanceDatabase equities file — **direct read of `compression/equities.bz2` (pinned commit SHA, cached locally; ~3 lines of pandas), not the pip package** (the package's sole dependency drags in scikit-learn/openpyxl for what is a CSV lookup — NFR7). License MIT (3-0 verified); 160k+ equities keyed by yfinance-compatible tickers with sector/industry/country/market-cap fields; US rows auto-update weekly, EU rows are community-maintained → treated as a starting list, re-verified at screen time.

`universe_config`: countries {US + EU set} · sectors/industries mapped to the circle (software/cloud, healthcare tech & services, AI tooling adjacents) · `exclude_delisted` · market cap ≥ Mid Cap · primary-listing dedup: **US leg via the no-dot filter, EU legs via exchange/market filters** — the library's `only_primary_listing` flag is a "no dot in ticker" heuristic that keeps US cross-listings (ASML) and drops Euronext home listings (ASML.AS); verified live. Universe refresh is a manual ritual (suggested quarterly), journaled as `config_or_designation`.

### H.2 Screen recipe (pre-committed config; human-run per FR14)

**One recipe in v1 — QV, quality-value (Greenblatt-derived)**, run via TradingView-Screener (human-triggered, results human-read, delayed data), intersected with the H.1 universe, capped at **top 20 ordered by the cheapness leg**:

- Cheapness leg (load-bearing, **pinned to one field** — MA-8): ascending `enterprise_value_ebitda_ttm` (the verified proxy closest to the evidence-bearing EBIT/EV; documented single-swap alternative: `price_free_cash_flow_ttm`).
- Quality cut (confirmatory): `return_on_invested_capital` > 15%.
- Guards: `debt_to_equity` < 1, positive TTM FCF.

Cheapness is load-bearing and quality confirmatory because independent evidence shows EBIT/EV carried most of the Magic Formula's alpha. The former second recipe (QA, Spitznagel-derived) is **cut from v1** — no independently reviewed evidence in either research doc; revisit condition documented, same pattern as FinanceToolkit (FS-F10). The former per-candidate canonical Magic Formula recomputation is also cut — the screen surfaces, the Gate dossier's owner-FCF picture judges; a bespoke NWC/NFA extraction path was machinery without a decision attached (F10/MA-10).

**Honest evidence note (printed on every screen output):** independent replications put quality-value screening at roughly 3–6%/yr gross outperformance with multi-year losing stretches — not the book's 30%. The screen *surfaces cheap, capital-productive businesses*; it promises nothing. Every candidate still passes the full Gate, and Greenblatt's own investor-behavior data shows second-guessing the screen's valuation call destroys the edge — the Gate judges the framework, not price timing.

### H.3 Candidate flow

Screen results → human eyes → hand-picked tickers enter the watchlist as `raw` (cap 10, 90-day expiry) with `idea_source: scout_screen` → the Gate. Screen output itself is discarded after the session; royalty-trust-style ROIC artifacts are the owner's to sanity-filter.

### H.4 What the Scout is not (evidence-based exclusions)

- **No momentum leg:** momentum pays at 3–12-month rotation horizons and reverses at the 3–5-year horizons this book holds at; a momentum rank hides exactly the "wonderful business on sale" candidates and is most wrong in post-panic rebounds. At most, fundamental-momentum may appear as display-only context, never as filter or rank.
- **No ESG factor:** JFE-level evidence is contested; not in the Constitution; not added.
- **No LLM stock-picking agents:** the "dual memory" citation traced to a paper-mill outlet; the credible line (FinMem/FinAgent/FinCon, arXiv) is day-trading agent research — citable as literature, off-framework as tooling. Its architectural insight *validates the existing design*: the Thesis Register + Decision Journal + Study **is** the long-term episodic memory; LLMs belong in qualitative thesis reasoning, deterministic code in all quantitative math.
- **No FinanceToolkit** (v1): MIT and keyless-capable (verified 3-0), but the Gate needs ~a dozen transparent ratios it already computes from hardened yfinance data, and the mandatory scikit-learn transitive stack fails NFR7 proportionality; its DCF invites assumption-stacking a fair-band system deliberately avoids. **Pre-approved revisit condition:** if Gate ratio needs outgrow ~10 formulas or statement normalization becomes a real maintenance burden, FinanceToolkit in custom-data mode is the verified fallback.
- **No FinQuant, no QuantMuse:** dormant/MVO-category and trading-execution-category respectively — both already-rejected categories.

---

## Traceability — every element earns its place

| Element | Requirement / Constitution rule |
|---|---|
| "No action needed" headline | FR4; Munger action bias |
| Opportunities vs owner's own anchor; invitation framing; fair-entry for WATCH | FR4; Pillar 1 "buy more on sale" and "wonderful business at a fair price"; FR11 |
| Owner-FCF (= FCF − SBC) as the owner-earnings figure and all denominators | Pillar 1 owner earnings over reported earnings (BUF-5) |
| Single anchor metric P_FCF | Pillar 1: owner earnings, not reported EPS (BUF-1) |
| Moat-linked trigger requirement | Pillar 1 moat checklist — falsifiable forever (BUF-4) |
| Conviction-tiered sizing advice | Pillar 1 "10–15 high-conviction positions" (BUF-3) |
| Dividend receipts line + reinvest reminder | Pillar 1 practical rule verbatim (BUF-2) |
| No P/L or cost basis in daily/weekly; records appendix quarterly | FR7; Munger sunk cost |
| Benchmark quarantine by absent input; single benchmark S&P 500 TR EUR | FR13; Munger envy; PFIC owner reality |
| Freshness gate; STALE/BOOTSTRAPPING never PASS; UNVERIFIABLE escalation | NFR1, NFR6; MA-1/MA-3 honesty |
| Alert quotes trigger + 10-year statement verbatim; WHAT THIS IS NOT | FR2, FR6, FR7, FR8, FR11; commitment device |
| Trigger-loosening guard with headroom echo; re-anchoring ritual | Munger commitment bias; NFR4 |
| No autonomous review transitions; no news scanning; no price triggers at all | Core data-flow principle; F2 |
| Hidden concentration: local-currency clusters, single N_eff floor | FR12 |
| Watchlist zero-automation, cap, expiry; re-pitch confrontation | FR14; Munger FOMO drain |
| Owner-only fields, no defaults, annual re-affirmation | FR9 |
| Status-buy flag from the owner's answer only | Naval wealth vs status; FR9 (F11) |
| Process/outcome 2×2; dangerous wins loudest; pass-review on stated reason; quarterly no-action ratio | FR8; Munger overconfidence; anti-envy |
| Displacement rule at 15; position/cluster caps; leverage tripwire | Pillar 1 concentration; Pillar 2 leverage veto |
| Backfill queue with on-pace quiet mode; pause mode freezing all counters; interaction contract; reconciliation-driven flows | FR1, FR8, FR13 integrity; NFR5; NAV-6/7 |
| Local storage + owner-only delivery | NFR2 (invariant 8) |
| Scout: human-triggered, one pre-committed recipe, capped output, evidence note | FR14/FR15; NFR7; Munger honesty |
| RunLog + immutable archive | NFR4 |

## Anti-complexity ledger (deliberately absent)

No news scanning · **no price triggers of any kind — decline or euphoria** (price appears only in buy-opportunity/fair-entry detection) · no automated idea generation · no ML/scoring/ranking of stocks · no portfolio weight optimization · no DCF engine · **single anchor metric: P/owner-FCF** (no EV, P_E, or P_S anchors in v1) · no milestone trigger type (dated questions ride the owner-attested type) · no momentum · no ESG scoring · no second benchmark · no second screen recipe · no daily portfolio value, P/L, euro amounts, or streak counters · no letter-grade process scores · no dual review clocks · no non-binding metrics (sector-weight knob and second N_eff floor deleted) · no automated counterfactual replay of revised data · no automation on raw watchlist items · no intraday anything. Every exclusion is tied to a Constitution failure mode or an NFR7 proportionality test; several carry documented revisit conditions rather than silent finality.

**Parked, unchanged:** technology/runtime; eToro API verification (the E.1 contract makes it a swap-in — the review's NAV-1 recommends ingestion automation as the *first* tech milestone); SEC EDGAR fallback; TradingView ToS posture (accepted, human-run only). **Review recommendations awaiting owner decision** (undefended or refuted-as-written, see review doc): question budget (NAV-2), Playbook rule-ledger (NAV-3), unified circle config (NAV-4), single consolidated config page (FS-F1).
