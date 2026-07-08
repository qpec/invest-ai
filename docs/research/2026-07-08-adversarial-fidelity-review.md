# Adversarial Fidelity Review — Design vs. the Original Buffett/Munger/Naval Thinking

**Date:** 2026-07-08 · **Method:** 47 agents. Five independent prosecutors (one per pillar: Buffett, Munger, Naval; two metrics auditors: availability & transparency, simplicity & comprehensibility) each tried to convict the design of infidelity to the original framework or of violating the owner's acceptance criterion. The 14 highest-severity findings then each faced **three independent defense counsel** trying to refute them; a finding stands only if ≤1 defender refutes it. 30 minor findings passed through labeled; 12 major findings overflowed the defense docket (marked *undefended*).

**Owner's acceptance criterion (binding):** *the requirements must describe a simple and understandable system, describable in terms of structured, transparent, available, and reasonable metrics.*

**Outcome: 9 convictions stand · 5 refuted · strong convergence in the minors.** All standing convictions plus the convergent minor fixes were applied to `docs/plans/2026-07-08-architecture-elaboration.md` on 2026-07-08 — nearly all deletions and clarifications; no new components.

---

## Prosecutor verdicts (summary)

- **Buffett:** "Impressively faithful on Munger mechanics… but Pillar 1 has been partially reduced to purchase-time paperwork. Buffett's load-bearing words are captured as fields and then not used." One critical (P_E/P_S re-admitting reported EPS into the fair-band machinery), four majors (dividend rule absent; conviction load-bearing nowhere; moat never re-falsified; SBC overstating owner earnings). *Seven of twelve fixes are deletions or one-line clarifications.*
- **Munger:** "The skeleton is acquitted; the accretions are convicted. The elaboration fails its own HN2 test: ~40 numeric assumptions, ~30 enum values, six parallel escalation mechanisms — while rejecting any stock that needs more than ~5 assumptions to value. Complexity addiction in the design itself." *Every proposed fix is a deletion or a merge.*
- **Naval:** "Split verdict. The monitoring core is genuine Naval leverage — code that compounds while the owner sleeps. But the periphery is a second job wearing a butler's uniform" (weekly manual exports, unbudgeted question queues, five-field journal forms, a 12-week nagged backfill). The learning loop "extracts lessons into a component with no store."
- **Metrics/availability:** "Everywhere the stack was live-verified the design is clean, and everywhere it wasn't, the design quietly assumes." Critical: the flagship growth trigger needs 6 quarters of history against a stack that returns 4–5.
- **Metrics/simplicity:** "**PASS WITH AMENDMENTS.** The design passes the owner's dinner-table test where it matters most: the Loop Spine states the whole system in one table the way the Constitution states each pillar."

---

## The docket — 14 findings, 3 defenders each

| # | Sev | Finding (short) | Defense votes | Verdict | Action |
|---|---|---|---|---|---|
| BUF-1 | crit | P_E/P_S anchors re-admit reported EPS / ignore cash | 0/3 refute | **STANDS** | ✅ Applied: P_FCF is v1's only anchor |
| MA-1 | crit | Default trigger persistence needs 6 quarters; stack returns 4–5 | 0/3 | **STANDS** | ✅ Applied: append-only FundamentalsCache archive + BOOTSTRAPPING state |
| F1 | crit | ~40-knob budget overrun; demand hard cap ~15 | 3/3 refute | REFUTED | Partially served by applied deletions; consolidation parked |
| NAV-1 | crit | Manual ingestion institutionalized as owner labor | 3/3 refute | REFUTED (as doc change) | Recommendation recorded: ingestion automation = first tech milestone |
| BUF-2 | maj | "Reinvest dividends" rule absent | 1/3 | **STANDS** | ✅ Applied: weekly dividends line + reinvest reminder |
| BUF-3 | maj | Conviction captured, never used; dangling sizing cross-reference | 0/3 | **STANDS** | ✅ Applied: conviction-tiered initial sizing (10/6/3%) + low-conviction question |
| BUF-4 | maj | No trigger required to test the moat claim | 0/3 | **STANDS** | ✅ Applied: `moat_link` — ≥1 trigger must test the moat |
| BUF-5 | maj | Raw FCF adds back SBC — overstated owner earnings in a SaaS circle | 1/3 | **STANDS** | ✅ Applied: owner-FCF = FCF − SBC everywhere |
| F2 | maj | Euphoria trigger = price trigger through a carve-out; no sell-when-expensive rule in the Constitution | 0/3 | **STANDS** | ✅ Applied: trigger type deleted; hard cap is the only trim advisory |
| F3 | maj | Modified Dietz over-engineering vs research-blessed approximation | 2/3 refute | REFUTED | Dietz stays; flow-confirmation lightened (MA-12) |
| F4 | maj | Six nag mechanisms → one Unresolved Ledger | 3/3 refute | REFUTED | As-is; drift-flag deletion (separate minor) applied |
| F5 | maj | Five prose fields per journal entry; falsifier duplicates the thesis | 0/3 | **STANDS** | ✅ Applied: merged fields; trigger-set default for buy/add |
| F6 | maj | Delete unverified officer-diff tripwire | 2/3 refute | REFUTED | Kept, with MA-6's verify-before-trust caveat applied |
| F7 | maj | Milestone trigger type + fourth cadence for a rare case | 0/3 | **STANDS** | ✅ Applied: type deleted; dated questions ride the owner-attested type |

## Undefended majors (overflow) — disposition

Applied (availability/honesty clarifications, convergent with standing convictions): **MA-2** (pinned net-debt/EBITDA rows; absent row → STALE), **MA-3** (non-positive/stale denominators suspend checks visibly), **MA-4** (non-mappable copyportfolios excluded from return/cluster series, weight printed), **MA-5** ("5y trends" → all-available-periods with printed count), **MA-6** (officer-diff: one-time verification required before trust), **FS-F3** (filings honesty: the owner is the filings sensor until EDGAR), plus the NFR2 functional one-liner (local storage, owner-only delivery).

Parked for owner decision (real design changes, not adversarially defended): **NAV-2** (question budget per week), **NAV-3** (Playbook — persistent rule ledger fed by quarterly reviews; currently lessons have no store), **NAV-4** (unified circle-of-competence config driving Gate, Scout and Study), **FS-F1** (single consolidated config page for all ~23 remaining constants).

## Convergent minors applied

Where two prosecutors independently hit the same target, the fix was applied: `fair_band_mid` defined (BUF-10/MA-9) · `fcf_ttm` construction pinned, empty period → STALE (MA-11) · WATCH items arm fair-entry only, opportunity is for held positions (F12/FS-F7) · `max_sector_weight` knob and second N_eff floor deleted — sector becomes a display column (F8/FS-F6) · status-buy price heuristic deleted, owner's answer is the only source (F11) · +100% shadow constant `<8` in the position band deleted (BUF-11) · `value_at_purchase` null for backfills (BUF-12) · statement-fingerprint promoted to authoritative earnings detector, calendar demoted to labeled preview (MA-7/BUF-6-adjacent) · automated revision-counterfactual replay deleted, pinning suffices (F9) · drift flag deleted, relaxation echo prints headroom-at-loosening (FS-F4) · daily streak counter deleted, no-action ratio moves to the quarterly process review (NAV-8) · pause mode freezes *all* counters (NAV-6) · `daily_letter_mode` config resolves the never-skipped/absence contradiction (NAV-9) · backfill nag weekly-only while on-pace (NAV-7) · daily cash as band-% only, no euro amounts (FS-F8) · flow confirmation only on unexplained reconciliation deltas (MA-12/BUF-9) · QV cheapness leg pinned to one field; QA recipe and canonical Magic-Formula recomputation cut from v1 with revisit conditions (MA-8/FS-F10/F10/MA-10) · journal decision-enum pruned, watchlist expiry moved to RunLog, expectation+falsifier merged (FS-F5).

Remaining minors are recorded in the workflow archive; none was load-bearing.

---

## The dinner-table test — every requirement in one plain sentence

The simplicity auditor's acceptance table (S/T/A/R = structured, transparent, available, reasonable). Failures found: 3, all fixed as noted.

| Req | One-sentence version | S·T·A·R |
|---|---|---|
| FR1 | I'm not allowed to own a stock unless I've written down why I own it — and anything I already own without that write-up gets flagged until it has one. | ✓✓✓✓ |
| FR2 | Every thesis answers the same short list: what the business does in two sentences, why it's protected, what cash it really makes, what price is fair, how sure I am, and exactly what would prove me wrong. | ✓✓✓✓ |
| FR3 | Before any real analysis, five quick disqualifying questions — failing even one kills the idea, no matter the upside. | ✓✓✓✓ |
| FR4 | Every market day the system checks my pre-set tripwires and price bargains, and usually tells me the best move is to do nothing. | ✓✓✓✓ |
| FR5 | Every Saturday the system refreshes the real numbers behind each thesis, re-tests every tripwire, and checks the portfolio is still balanced. | ✓✓✓✓ |
| FR6 | When a company reports earnings, files something important, or changes leadership, its thesis gets checked immediately instead of waiting for Saturday. | ✓✓**✗**✓ → fixed: filings leg honestly owner-attested; calendar labeled best-effort |
| FR7 | Each thesis is either fine, being questioned, or dead — and a dead thesis means sell advice no matter what I paid. | ✓✓✓✓ |
| FR8 | Every decision gets written down with my reasoning at that moment, and later I grade how I decided, never what the price did. | ✓✓✓✓ |
| FR9 | The system may never guess my confidence, my trust in management, or whether I truly understand the business — it always has to ask me. | ✓✓✓✓ |
| FR10 | My crypto and copy-portfolios still show up in the overall picture, honestly labeled as outside the rules, without pretending they have a thesis. | ✓✓✓✓ |
| FR11 | The system tells me what it thinks; only I ever place a trade. | ✓✓✓✓ |
| FR12 | Once a week the system checks whether my dozen holdings are secretly just three or four bets that all move together. | ✓✓✓✓ |
| FR13 | Once a quarter — and only then — I look at whether a plain index fund would have beaten my whole process. | ✓✓✓**✗** → fixed: flow confirmation reconciliation-driven; approximation caveats printed |
| FR14 | The system never goes hunting for stock ideas on its own — I have to go looking, and anything I find still passes the full Gate. | ✓✓✓✓ |
| FR15* | When I do go idea-hunting, I run one pre-agreed screen over a pre-agreed universe, read the top twenty myself, and throw the list away afterwards. | ✓✓✓✓ |
| NFR1 | If a data feed dies, the system keeps going on the last numbers it saw and says plainly how old they are. | ✓✓✓✓ |
| NFR2 | My portfolio data stays mine and never leaks anywhere. | **✗**✓✓✓ → fixed: functional rule added as global invariant 8 |
| NFR3 | Start with free data and pay only when free demonstrably falls short. | ✓✓✓✓ |
| NFR4 | Anything the system ever told me can be reconstructed later exactly as it was said, with the data it saw at the time. | ✓✓✓✓ |
| NFR5 | The system should run for months without me having to fix or fiddle with anything. | ✓✓✓✓ |
| NFR6 | Never trust a Yahoo number blindly: cache it, pace the requests, notice when the answer is empty, and clean the share-count series before using it. | ✓✓✓✓ |
| NFR7 | Only permissively-licensed, lightweight dependencies, and each one must remove more complexity than it adds. | ✓✓✓✓ |

*FR15 as proposed in `2026-07-08-longterm-id-frameworks.md`.

---

## Net effect of the applied amendments

Deleted: 2 trigger types (euphoria, milestone) · 1 trigger cadence value (`dated`) · 1 data source from the trigger schema (`yf_price`) · 1 daily check · 2 non-binding metrics (sector-weight knob, second N_eff floor) · 1 shadow constant (`<8`) · the status-buy price heuristic · the drift flag · the streak counter · the automated revision replay · 1 screen recipe (QA) · the Magic-Formula recomputation path · 2 journal prose fields · 1 journal decision type.
Clarified/pinned: owner-FCF definition · anchor restricted to P_FCF · fcf_ttm and net-debt/EBITDA row pinning · fair_band_mid · BOOTSTRAPPING state · available-period honesty · denominator suspension rules · non-mappable-instrument contract · filings/calendar honesty · officer-diff verification precondition · NFR2 rule · pause-mode scope · daily-letter mode.
Added (the only additions, all Constitution-mandated): moat_link rule (one field + one activation rule) · conviction-sizing table (one config row) · weekly dividends line (one report line).

**Owner decision 2026-07-08:** the proposals that failed the adversarial test — NAV-1 (as doc change), NAV-2 (question budget), NAV-3 (Playbook), NAV-4 (unified circle config), FS-F1 (single config page) — are **not adopted**. The docket is closed; the design stands as amended.
