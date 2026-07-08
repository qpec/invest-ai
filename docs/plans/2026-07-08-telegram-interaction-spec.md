# stock-agentcy — Telegram Interaction Specification

**Status:** Spec (not code). Drafted 2026-07-08; **amended the same day by the technology-architecture judge panel** (three convictions applied: the first-come-first-served `/start` bind was replaced by a pre-provisioned owner chat-id — §1.1/§5.1; weekly delivery is headline-first — §2.2; the formatting mode is locked to HTML — §2/§8). Companion to `docs/plans/2026-07-08-technology-architecture.md`. Binding functional sources: `docs/plans/2026-07-08-architecture-elaboration.md` (components A–H, 8 invariants, loop spine, trigger taxonomy, outputs G.1–G.4, anti-complexity ledger) and `docs/plans/2026-07-08-functional-design-baseline.md` (FR1–FR14, NFR1–NFR7). Constitution: `CLAUDE.md`.

**What this document decides:** the exact shape of every Telegram message the bot sends, every button the owner can tap, the callback-data grammar that carries stable ask-IDs, how free-text evidence is captured and journaled, and the security/delivery/degradation behavior. It does NOT decide runtime code structure, DB schema, or the desk-side Claude Code authoring flows (out of scope — Gate prose, Scout screens, Study restudy all enter as owner-typed data, never via the bot).

**Design premise (owner-locked 2026-07-08):** one private bot chat, one owner chat-id, long-polling (no inbound ports, no webhook), no LLM in the scheduled runtime, SQLite source of truth + markdown/git mirror. Every scheduled output is a deterministic template. The bot is a *courier and a clipboard*: it delivers deterministic reports and it collects enumerated answers plus committed free-text fields. It never analyzes.

---

## 0. Governing principle for this interface: tap-first, and even taps are rare

This bot inverts the usual "minimize typing" rule into something stricter. The Constitution's highest-value output is **"no action needed"** (FR4). Most days the bot sends one message and expects zero interaction. Interaction happens only when the system has a *pre-committed question* to ask — a fired trigger, a prompted trigger question, a reconciliation delta, an annual re-affirmation. Every such ask is a first-class object (D.5) with a stable ID and an enumerated reply set. Free text is required in exactly three places and each is structurally bound to its ask.

**The register is load-bearing, not cosmetic (G global rules):**

- No exclamation marks anywhere in alert, trigger-question, or reconciliation templates.
- No red-alarm typography, no 🔴 / 🚨 / ⚠️ emphasis on prices, ever. The single check-mark ✓ marks the *calm* state ("no action needed"); it is the only celebratory glyph.
- "No action needed" is the headline, never the fine print.
- Staleness is always stated in-band, never hidden.
- Advice, never instructions. Every actionable line closes with an invitation ("this is an invitation, not an instruction"), never an imperative.
- No portfolio value, no P/L, no euro cash amounts in the daily letter (owner decision 2026-07-08; cash is band-% only). Value lives in the weekly review; cost basis lives only in the quarterly records appendix.
- No streak counters, no gamification, no self-benchmarking outside the quarterly report.

These are enforced **structurally** — they live in the template strings and in a lint step over outgoing text (§8), not in the discretion of whoever writes a message.

---

## 1. Command surface

Commands are deliberately few. This is a single-owner bot; the owner already knows what it does. Commands exist only where the owner must *pull* state or *change* the system's mode between scheduled runs. Everything else the bot *pushes*. Each command below is justified; anything not listed was considered and rejected (§1.8).

Registered via `setMyCommands` (private-chat scope, owner chat only). The Telegram command menu is the owner's whole navigation surface — there is no persistent reply keyboard (a reply keyboard would clutter a chat whose defining property is quiet).

### 1.1 `/start` — orientation only (owner chat-id is pre-provisioned, never bound in-chat)

**Purpose:** orientation. **The owner chat-id is provisioned at install time** in the 0600 `EnvironmentFile` next to the bot token, before the bot ever polls — there is no in-chat binding step. *(Amended by the judge panel: a first-come-first-served Confirm button meant whoever discovered the bot username first became the sole allowlisted recipient of every portfolio output — a race that contradicts "locked to the owner's chat id", NFR2, and invariant 8.)*

`/start` (from the pre-provisioned owner chat, any time, idempotent) prints:
```
stock-agentcy is online, locked to this chat.

I monitor the theses behind your holdings and tell you when the reason
you bought something no longer holds. I advise; I never trade.

What I send, and when (Europe/Amsterdam):
• Daily letter — every morning; the full letter on US market days,
  a two-line pulse on weekend mornings. Its absence is the alarm.
• Weekly review — Saturday morning (the deep one; nothing can be traded impulsively then).
• Quarterly honesty report — once a quarter.
• Alerts — only when a trigger you committed to fires. Never for price moves.

Commands: /status  /pause  /resume  /event  /snapshot  /help
```

**Re-binding** (new phone/account) is a desk-side operation: edit the EnvironmentFile, restart the bot unit, journaled as `config_or_designation`. A stolen phone cannot redirect the feed with one command; neither can a stranger who finds the bot before the owner does.

**Onboarding does NOT collect any thesis, conviction, or judgment field.** All FR9 owner fields are authored at the desk (Claude Code session) and enter via SQLite. The bot's onboarding is pairing + orientation only.

### 1.2 `/status` — pull the current calm state (read-only)

**Purpose:** the owner wants the one-screen picture *right now*, between letters. Justified because the daily letter is a snapshot in time; the owner may check at 15:00 before the letter exists, or re-read without scrolling.

Returns a compressed live status card — the G.1 header block plus any open loops, and nothing else:

```
Status — Tue 8 Jul 2026, 14:12 CET

Snapshot: manual export of Sun 6 Jul (2 days old)
Prices: fresh (07:00 CET)  ·  Cash 8.1% (band 5–15% ✓)
11 framework · 1 backfill pending · 2 outside-framework

✓ All theses intact. No triggers fired. No open decisions.

Next scheduled: daily letter after tonight's US close.
```
If open loops exist (under_review past deadline, alert_ignored, broken-but-held, unanswered prompts), they are listed here as one-liners with their ask-IDs, each tappable to resume (§3). `/status` never runs checks — it reports the last RunLog state and says how old it is. No inline keyboard unless open loops exist.

### 1.3 `/pause [window]` and `/resume` — pause mode (D.6)

**Purpose:** owner declares an absence window. Freezes all deadline/skip counters (alert windows, prompted-question skips, re-affirmation skips, UNVERIFIABLE week counts) so a vacation does not pollute the FR8 record with fake "ignored" decisions. Justified: this is the single most important owner-driven mode change and must be one tap-plus-choice, reachable from a phone anywhere.

`/pause` with no argument opens a choice keyboard rather than demanding typed dates (tap over type):
```
Pause mode. Deadlines and skip counters freeze. Alerts still arrive;
weekly reviews still run. Daily letters: your choice below.

How long?
```
Inline keyboard (one column):
```
[ Until I resume (open-ended) ]      pause:set:open
[ 1 week ]                           pause:set:7d
[ 2 weeks ]                          pause:set:14d
[ Custom end date… ]                 pause:set:custom
```
After a duration is chosen, a second row sets `daily_letter_mode` (D.6):
```
[ Keep daily letters (default) ]     pause:mode:always
[ Quiet — suppress daily letters ]   pause:mode:quiet
```
"Quiet" still runs checks and logs to RunLog daily; it suppresses only the letter, never an alert. Confirmed with a plain calm sentence stating the freeze scope and, if a window was set, the resume date. `/pause` optionally accepts an inline shorthand for power use (`/pause 2w quiet`) — but the tap path is canonical and the shorthand simply pre-fills the same confirmation.

`Custom end date…` uses the date-picker keyboard (§3.7) — never ForceReply for a date, because a date is enumerable.

`/resume` ends the window immediately, journals pause-off, prints how many counters were frozen and are now live again, and — critically — surfaces anything that accrued while paused (e.g. "2 prompted questions are waiting; their skip counters start now"). No dead-ends.

**Journaling:** pause-on and pause-off each write a JournalEntry (`config_or_designation`), per D.6.

### 1.4 `/event <TICKER>` — owner-injected event check (FR6)

**Purpose:** the owner is a first-class sensor (D.3b, FR6). They read something — a filing, a management change, a news item — and want an immediate single-holding check against that thesis's committed triggers. Justified: FR6 names owner ad-hoc event entry explicitly; filings detection is owner-attested until EDGAR is adopted, so this is the *only* channel for the owner's filing sensor.

`/event` with no argument lists held+backfill tickers as an inline keyboard (tap over type — the owner should not have to remember the exact symbol):
```
Which holding had an event? (earnings, filing, management change)
```
Keyboard: one button per framework/backfill ticker, `evt:pick:<thesis_id>`, paginated at 8 per screen (§3.8 pagination). A final row: `[ It's a ticker not shown / new position ]` → ForceReply for the symbol (the rare typed case, because an unknown symbol is not enumerable), which then routes through E.1 reconciliation.

On ticker pick, the bot asks the event class (so the event report labels itself honestly):
```
{TICKER} — what kind of event? (used to label the check; does not change the triggers tested)
```
Keyboard:
```
[ Earnings / new statements ]   evt:kind:<thesis_id>:earnings
[ Filing ]                      evt:kind:<thesis_id>:filing
[ Management change ]           evt:kind:<thesis_id>:mgmt
[ Other / I'll note it ]        evt:kind:<thesis_id>:other
```
`Other` opens a one-line ForceReply for the note. The event check then runs deterministically (fresh statements bypass cache, all armed triggers for that thesis re-tested, prompted questions queued with the event named — D.3). The bot replies with the acknowledgement immediately (`sendChatAction: typing` while it runs), then the event report (§2.4). If the data lags (post-earnings), it says so and states the 7-day retry (D.3 degradation) — the prompted questions are put to the owner immediately regardless (they do not wait for data).

`/event` never scans news. It only re-tests pre-committed triggers for one named holding — the core data-flow principle made literal.

### 1.5 `/snapshot` — how a manual export gets in (E.1 ingestion)

**Purpose:** the Portfolio Mirror is source-agnostic (E.1); in manual mode the owner supplies exports. Justified: without an ingestion path there is no fresh Snapshot, and the operating contract (E.1) expects a weekly export before the Saturday run and one after any trade.

`/snapshot` opens the ingestion chooser:
```
Add a portfolio snapshot. Attach a file or paste positions — I'll
reconcile it against what I last saw and ask about anything I can't explain.
```
Keyboard:
```
[ Upload export file (CSV) ]     snap:mode:file
[ Paste positions as text ]      snap:mode:text
[ Cancel ]                       snap:cancel
```
- **File:** the owner sends a document (CSV export from eToro or any adapter). The bot receives it via the normal document handler, runs the E.1 CSV adapter to the canonical contract, and proceeds to reconciliation. No ForceReply needed — a document upload is its own signal.
- **Text:** ForceReply prompt with a one-line format reminder; the paste is parsed by the manual-entry adapter.

After parse, the bot runs **reconciliation on every snapshot** (E.1) and, for each delta it cannot explain, emits a reconciliation prompt (§3.4). If everything reconciles, it confirms plainly:
```
Snapshot accepted — as of {as_of}. 11 positions, cash 8.1%. Everything reconciles.
Weights refresh on the next run.
```
The snapshot is stored append-only; nothing is destructively overwritten (invariant 1). The bot states the new snapshot age so staleness is always visible.

`/snapshot` is the only command that accepts an uploaded file, and it accepts a file **only** immediately after `snap:mode:file` (state-scoped — see §4). A document sent cold, with no pending snapshot state, is answered with a gentle redirect to `/snapshot`, never silently ingested (a stray file must not become portfolio truth).

### 1.6 `/help` — quick reference (read-only)

Terse. Lists the six commands with one calm line each and restates the cadence. Ends with the standing invariant: *"I advise and monitor. I never trade. I only ever ask you things you pre-committed to answer."* No inline keyboard — help is a leaf.

### 1.7 Command summary table

| Command | Purpose | Justification (why it earns a slot) | Writes state? |
|---|---|---|---|
| `/start` | Pair + orient | Must bind the owner chat-id once; idempotent thereafter | Config (bind, once) |
| `/status` | Pull calm state now | Daily letter is point-in-time; owner may check between letters | No (reads RunLog) |
| `/pause` / `/resume` | Absence mode (D.6) | Freezes counters so a vacation doesn't fake "ignored" decisions | Journal + config |
| `/event <TICKER>` | Owner-injected event (FR6) | Owner is the filings/news sensor; only channel for it | Event report + journal if fired |
| `/snapshot` | Ingest export (E.1) | No ingestion path = no fresh Snapshot; manual-mode contract | Snapshot (append-only) + journal on reconciliation |
| `/help` | Reference | Leaf; restates cadence and the advise-only invariant | No |

### 1.8 Commands deliberately NOT added (fewer is better)

- **`/thesis`, `/register`, `/gate`** — thesis viewing and authoring live at the desk (Claude Code + markdown/git mirror). Putting a thesis editor in Telegram would invite exactly the free-text, unversioned mutation the Constitution forbids (invariant 1, FR9). The weekly review already carries the thesis scorecard; the git-mirrored thesis markdown is the readable copy.
- **`/report` / `/weekly` / `/quarterly` on demand** — reports are scheduled, deterministic, and archived. An on-demand re-run invites the daily self-benchmarking envy loop the design explicitly deletes (F.2, G global rules). The owner re-reads the archived message or the git markdown mirror instead. `/status` covers the "what's true now" need without re-running analysis.
- **`/watchlist` add** — watchlist entry is human-triggered at the Gate (FR14, C.1); a one-tap "add ticker" button would erode the Gate discipline. The Scout and Gate are desk rituals.
- **`/settings`** — balance bands, discount, alert window are config; changes must be journaled and are rare (E.3). They are edited at the desk with a journaled reason, not fat-fingered on a phone.
- **A persistent reply keyboard / main-menu button** — rejected. The chat's defining quality is silence; a standing keyboard is visual noise that implies there is always something to do, contradicting FR4. The command menu is sufficient.

---

## 2. Message layouts (mapped from G.1–G.4)

All messages use **`parse_mode=HTML`, locked** *(amended: the panel closed the earlier "MarkdownV2 or HTML" openness — MarkdownV2 requires escaping 18 characters including `.` and `-`, the verified silent-failure footgun for generated financial text; HTML needs only `& < >` through one escaper)*. Every dynamic field is escaped through it (§8); ticker symbols, multiples, and owner free-text are the escape-sensitive fields. Layouts below are shown as rendered text.

### 2.0 The "one phone screen" property — how it is preserved

The daily letter, `/status`, and each Study digest are **hard-budgeted to fit one phone screen without scrolling** on a standard portrait device (~ up to 12–14 short lines, well under 4096 chars). This is preserved by construction:

- The daily letter has a fixed skeleton: header (2 lines) + verdict line + at most one OPPORTUNITIES block + at most one EVENTS line + one DATA line. Opportunities are the only expandable section, and each opportunity is capped at 3 lines; if more than 3 tickers qualify, they are ranked by position weight and the letter shows the top 3 with a tail line "+N more in the weekly review" — the daily letter never grows past a screen (this preserves G.1's "fits one phone screen").
- No section that can be unbounded (full portfolio table, cluster matrix) ever appears in the daily letter. Those live only in the weekly review, which is explicitly allowed to be long (§2.2).

### 2.1 Daily letter (G.1) — one Telegram message, never skipped

Maps G.1 verbatim in structure. Single `sendMessage`. The subject line becomes a **bold first line** (Telegram has no subject field).

```
Daily letter — Tue 8 Jul 2026 — ✓ No action needed

Snapshot: manual export of Sun 6 Jul (2 days old) · Prices: fresh (07:00 CET)
Cash 8.1% (band 5–15% ✓) · 11 framework · 1 backfill pending · 2 outside-framework

✓ No triggers fired. All theses intact. Doing nothing is today's best move.

OPPORTUNITIES (held intact theses, cheap vs YOUR anchor — this is what you wait for):
• DDOG — 24× P/FCF vs your fair band 28–36× (thesis v2, intact, 4/4 triggers pass)
  ON SALE — ≥20% below your own anchor. Cash band ✓ (8.1%).
  Re-read the thesis first; this is an invitation, not an instruction.

EVENTS: MSFT earnings expected 24 Jul (16 days, calendar estimate) — event check
  will run automatically on detection.
DATA: all sources fresh.
```

- **No inline keyboard on a calm daily letter.** A "no action needed" day has nothing to tap. Buttons appear on the daily letter only when it *carries an open-loop escalation* (an `alert_ignored` heading the letter per B.3.3, or a broken-but-held renag) — in which case the relevant ask's inline keyboard (§3) rides on that letter so the owner can resolve it in place.
- **Degraded-day variant** (G.1), single message, still sent, still no red typography:
```
Daily letter — Wed 9 Jul 2026 — checks suspended

Checks suspended — prices stale since Thu 3 Jul.
Nothing is wrong; I just can't see. Last known: positions as of Sun 6 Jul.
The letter resumes full checks when data returns.
```
- **Total failure variant** (G.1): *"Data sources unavailable since {t}; last known state; no checks performed. Nothing is wrong; I just can't see."* Always sent.

### 2.2 Weekly review (G.2) — exceeds 4096; splitting strategy

The weekly review has nine sections (G.2) including a full portfolio table and a correlation matrix — it will exceed Telegram's 4096-char single-message limit. **Chosen strategy: BOTH — a numbered message series for glanceable sections, plus `sendDocument` of the full markdown as the authoritative archived copy.** Rationale below.

**Delivery order** *(amended: headline first — "no action needed is the headline" means the verdict must hit the glass before any attachment)*:

1. **First the numbered message series** of the *glanceable* sections, each its own `sendMessage`, so the owner gets the verdict and the decisions on-screen without opening a file. The series is capped and ordered by decision-urgency:

   - **Msg 1/N — Headline verdict** (G.2 §1). Celebrated if "no action needed"; UNVERIFIABLE escalations surface here. Carries the "full detail in the document that follows" pointer.
   - **Msg 2/N — Decisions waiting** (only if any): open reviews, prompted questions due, anniversary re-affirmations due, backfill next-in-queue, broken-but-held renags. **This is the only weekly message that carries inline keyboards** — one ask per block, each with its stable-ID keyboard (§3). If nothing is waiting, this message is replaced by a single celebrated line: *"No decisions waiting. The document has the full picture when you want it."*
   - **Msg 3/N — Balance & concentration snapshot** (G.2 §4 compressed): cash band, position-count band, N_eff vs 4.0 floor, any breached band as a one-liner, dividend-idle reminder if applicable. The full cluster table and correlation matrix stay in the document only (a matrix does not render on a phone).
   - **Msg 4/N — The Study** (G.2 §8 / F.3): capped at one screen by its own spec. The restudy note, the one mental-model prompt, the reading-queue line. The circle-note ForceReply (§3.9) rides here if the owner chooses to answer.

   The portfolio table (§2), full thesis re-validation paragraphs (§3), outside-framework block (§5), watchlist (§6), and data-health appendix (§9) live **in the attached document only** — they are reference, not decisions, and the owner reads them in the file. This keeps the message series to ~4 short messages regardless of portfolio size.

2. **Then `sendDocument`** of the full weekly review as `weekly-review-2026-07-11.md` (the same markdown auto-committed to git — one artifact, two homes; NFR4 twice over). This is the complete, canonical, scrollable, searchable copy and the thing the owner keeps.

**Why both, not one or the other:** a pure numbered series fragments the table and matrix into unreadable stubs and floods the chat; a pure document hides the verdict and the waiting decisions behind a tap, defeating the "no action needed is the headline" rule. The split puts *decisions on the glass* and *reference in the file*. The prompted-question keyboards must be tappable inline, so they cannot live only in a document — this alone forces the hybrid.

### 2.3 Quarterly honesty report (G.4) — `sendDocument` + one summary message

The quarterly report is the only place a benchmark exists (FR13, quarantined) and it is long (seven sections including the records appendix with cost basis). **Strategy: `sendDocument` of the full markdown, preceded by a single summary `sendMessage`** carrying only:

- G.4 §1 "the honest question" one-liner (portfolio EUR vs S&P 500 TR EUR, since-inception lead; single quarter shown last and smallest with "do not extrapolate 13 weeks");
- G.4 §2 "the honest answer" — the one written sentence;
- the standing reminder: *"The 10-year answer is the real one."*

No inline keyboard on the quarterly summary — its decisions (journal grading) are a desk ritual (F.2, "one honest hour per quarter"), not a phone tap. The report's flow-approximation and unpriced-weight caveats and the indexing-exit clause live in the attached document. The benchmark, cost basis, and P/L appear **only** in this attachment — never leaking into the summary message (the quarantine is an absent input, not a suppressed section — invariant 7).

### 2.4 Event report (D.3) — quiet outcome vs fired

- **Quiet outcome** (no trigger fired): the event check produces **no separate ping**. It becomes one line in the next daily letter (D.3): `{TICKER} earnings checked; n/n triggers pass; no action needed.` If the check was owner-initiated via `/event`, the bot additionally sends one immediate calm acknowledgement so the owner knows their request landed:
```
{TICKER} — {event kind} checked against your committed triggers.
{n}/{n} pass. Thesis intact. No action needed.
Full check archived. This also appears as one line in tomorrow's letter.
```
- **Data-lag outcome:** `{TICKER} — statements not yet updated after {event}. I'll retry daily for 7 days. Your prompted questions (below) do not wait for the data.` — followed immediately by any prompted trigger questions (§3.2).
- **Fired outcome:** an **Alert** (§2.5), not an event report — a fire always escalates to the alert path (B.3.1).

### 2.5 Alert (G.3) — the only unscheduled push

Maps G.3 verbatim. Single `sendMessage` with an inline keyboard (§3.3). The **WHAT THIS IS NOT block is reproduced verbatim** from G.3 and is mandatory in every alert:

```
Trigger fired — CRWD — T2 (owner-FCF margin) — decision by Tue 14 Jul (7 days)

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
Inline keyboard: `[ Confirm broken ]` `[ Refute ]` — two buttons only at first presentation; **`Revise` is not shown until after a refute** (§3.3, goalpost guard A.3). No exclamation marks; the −9% price is stated flatly and immediately disowned. The header says "decision by {date}" not "URGENT".

**Storm variant** (B.3.5) — one bundled message, items ranked by position weight, one shared deadline:
```
Triggers fired — 3 theses — one decision window, by Tue 14 Jul (7 days)

A market-wide move can fire several theses at once. Take them in order of weight;
there is no rush beyond the shared deadline. Each is a separate decision.

1. CRWD (9.2% of book) — T2 owner-FCF margin < 20% (2q): Q1 18.4%, Q2 17.1%.
2. DDOG (7.1%) — T1 revenue YoY < 10% (2q): 9.1%, 8.4%.
3. NET (4.3%) — T4 dilution > 3%/12m: 3.6%.

Cost basis is not shown for any of these and will not be considered.
Open each below to see its committed statement and your 10-year words.
```
Inline keyboard: one row per item — `[ 1. CRWD ]` `[ 2. DDOG ]` `[ 3. NET ]` (callback `alert:open:<alert_id>:<thesis_id>`), each expanding into that item's full G.3 alert card with its own confirm/refute buttons. One shared `deadline`, one shared `alert_id`, per-thesis resolution journaled independently.

---

## 3. Inline keyboards, callback grammar, and every ask-flow

### 3.1 Callback-data grammar (carries the stable ask-ID)

Telegram limits `callback_data` to 64 bytes. Grammar is colon-delimited, versioned, and every ask-bearing callback carries the ask-ID so the reply journals against the exact object (D.5):

```
<domain>:<action>:<ask_id>[:<value>][:v<n>]
```

- `domain` ∈ { `alert`, `trig`, `recon`, `reaff`, `pause`, `evt`, `snap`, `sys`, `page` } — 2–5 chars.
- `action` — the verb (`confirm`, `refute`, `revise`, `yes`, `no`, `cant`, `open`, `set`, `pick`, `kind`, `bind`, `nav`).
- `ask_id` — the **stable ask identifier**, the spine of D.5. Format `<K><seq>` where `K` is a one-char kind (`A`=alert, `Q`=prompted trigger question, `R`=reconciliation, `F`=re-affirmation) and `seq` is a monotonic integer, e.g. `A238`, `Q1041`, `R77`, `F19`. The ask_id is minted when the ask is created and stored in SQLite with its enumerated option set, its thesis/trigger reference, its deadline, and its state {open, answered, reprompted, unanswered, frozen}. **The button carries only the ask_id and the chosen option** — never the payload — so 64 bytes is never at risk regardless of ticker length or free-text.
- `v<n>` — an optional grammar/version guard so a stale button from an old message can be detected and refused (§3.10).

Examples:
```
alert:confirm:A238            confirm-broken on alert A238
alert:refute:A238             refute path (opens ForceReply for evidence)
alert:revise:A238             (only rendered after a refute is recorded)
trig:yes:Q1041                prompted trigger question Q1041 → yes
trig:no:Q1041                 → no
trig:cant:Q1041               → can't-verify (opens ForceReply for the note)
recon:pick:R77:close          reconciliation R77 → journal as position close
reaff:set:F19:conviction:hold re-affirmation F19, conviction unchanged
page:nav:evtpick:2            pagination, event-picker, page 2
```

**Every inbound callback is validated against SQLite before any effect:** the ask_id must exist, be open (or in an allowed state), belong to this owner, and the chosen option must be in that ask's enumerated set. A callback that fails validation is answered with `answerCallbackQuery` ("This choice is no longer available") and dropped — never trusted (§5.4). Client data is never authoritative.

### 3.2 Prompted trigger question {yes / no / can't-verify + note}

The type-5 owner-attested trigger (B.2) puts a pre-committed binary question to the owner at each earnings event, or weekly if flagged urgent. It is ask-kind `Q`.

Message:
```
Prompted check — VEEV — T3 (owner-attested), Q1041
Committed question (thesis v2, your words):
  "Has the founder-CEO departed or announced departure?"
Context: Q2 earnings, statements refreshed today.
This is a yes/no you pre-committed to answer. No price is involved.
```
Inline keyboard (one row):
```
[ Yes ]            trig:yes:Q1041
[ No ]             trig:no:Q1041
[ Can't verify ]   trig:cant:Q1041
```
Flow:
- **Yes** → the trigger's committed logic determines the effect. If "yes" means the trigger condition is met (e.g. the departure happened), the trigger **FIREs** → thesis → under_review → an Alert (§2.5) is generated for the *broken-thesis question* (the prompted question established the fact; the alert asks the interpretive question). If "yes" means the reassuring answer, it records PASS. The mapping of yes/no→FIRE/PASS is stored per trigger at commit time, so the button meaning is unambiguous and deterministic. The message states which is which by quoting the committed statement, so the owner is never guessing.
- **No** → records the opposite verdict; journaled with the ask_id.
- **Can't verify** → opens a **ForceReply** for the mandatory note (D.5 `{yes, no, can't-verify + note}`). The note is journaled with the ask_id and the trigger reports **UNVERIFIABLE** for this cycle. UNVERIFIABLE is never green (B.3.4): the standard escalation applies — surfaced in every review, and **3 consecutive unverifiable weeks escalate to the weekly headline**.
- Each answer edits the original message (via `editMessageText`) to show the recorded choice and remove the keyboard, so the chat shows resolved state and the button can't be tapped twice (§3.10).

### 3.3 Alert responses {confirm broken / refute (requires evidence) / revise (only after refute)}

Ask-kind `A`. The alert card (§2.5) presents **two** buttons initially:
```
[ Confirm broken ]   alert:confirm:A238
[ Refute ]           alert:refute:A238
```
- **Confirm broken** → a **confirmation step** (this is irreversible advice — sell advice, cost basis ignored), because a mis-tap here is costly:
  ```
  Confirm: the thesis for CRWD is broken. This produces sell advice for the full
  position, ignoring cost basis. The thesis moves to broken (terminal — a new
  position later needs a fresh Gate run). Proceed?
  ```
  Keyboard: `[ Yes, thesis is broken ]` `alert:confirm2:A238`  ·  `[ Go back ]` `alert:back:A238`. On confirm: `trigger_resolution[confirmed_broken]` journaled, thesis → broken, sell advice issued (deterministic template), message edited to the resolved state. No exclamation marks even here.
- **Refute** → **requires written evidence** (B.3.2). Opens a **ForceReply**: *"Refuting T2 for CRWD. Write the evidence that the reason you own this still holds. This is journaled verbatim and re-arms the trigger."* The reply text is captured (§4), journaled as `trigger_resolution[refuted]` with the evidence verbatim, thesis returns to `intact`, the trigger re-arms. **Only after a refute is recorded** does the bot edit the message to add the third option:
  ```
  Refute recorded. Trigger re-armed; thesis intact.
  If refuting means the trigger itself was mis-specified, you may now revise it.
  ```
  New button appears: `[ Revise the trigger ]` `alert:revise:A238`. This is the *only* way `revise` becomes available — enforcing goalpost guard A.3 ("you may not move the goalposts while the ball is in the air; during review, revise is possible only after an explicit refute"). Revise itself routes to the desk: the bot does **not** edit trigger thresholds via free text on a phone (that is a versioned thesis mutation, A.3). Instead it records the *intent to revise* with a mandatory note and prints the standing echo requirement: *"Trigger revision is a versioned change — make it at the desk. I've journaled your intent and will echo the loosening with its headroom for 4 weeks (A.3)."*
- **No response by deadline** → `alert_ignored` auto-journaled (B.3.3), heads every daily letter until resolved, thesis stays `under_review`. During pause mode the deadline counter is frozen (D.6).

### 3.4 Reconciliation prompts (E.1) — appeared / disappeared / quantity change / unexplained cash

Ask-kind `R`, minted during `/snapshot` reconciliation (§1.5) or an `api_pull`. One prompt per delta. The reconciliation closes the FR8 loop for off-system trades.

**New ticker without a thesis (appeared):**
```
Reconciliation — R77 — new position: ASML, 12 shares, not previously seen.
How should I treat it?
```
```
[ Backfill thesis (equity, needs a Gate run) ]   recon:pick:R77:backfill
[ Outside framework (ETF/crypto/copyportfolio) ] recon:pick:R77:outside
[ This is a data error — ignore ]                recon:pick:R77:ignore
```
`backfill` → position marked `backfill_pending`, enters the backfill queue by weight (C.6). `outside` → designated `outside_framework` (the once-only designation prompt, E.1/E.2), journaled `config_or_designation`. `ignore` → flagged for re-check, not stored as truth.

**Disappeared ticker:**
```
Reconciliation — R78 — CRWD no longer appears in the snapshot (was 9.2%).
Did you close it?
```
```
[ Yes — journal the close ]        recon:pick:R78:close
[ No — data/export gap ]           recon:pick:R78:gap
```
`close` → prompts (ForceReply) for the one-line reasoning-at-the-moment (`sell` decision, F.1 mandatory reasoning), journaled; if the thesis was intact the journal notes advice was not the driver. `gap` → position carried at last-snapshot value, flagged in data-health.

**Quantity change (add/trim):**
```
Reconciliation — R79 — MSFT quantity changed 40 → 55 (+15). Add?
```
```
[ Added to position ]     recon:pick:R79:add
[ Trimmed ]               recon:pick:R79:trim   (shown when quantity fell)
[ Data error ]            recon:pick:R79:gap
```
`add`/`trim` → ForceReply for reasoning-at-the-moment, journaled `add_to_position`/`trim` with `inputs_ref` pinned. For a buy/add, `expectation_and_falsifier` defaults to the committed trigger set (the thesis IS the falsifier, F.1) — no new prose demanded.

**Unexplained cash delta (MA-12):**
```
Reconciliation — R80 — cash moved by +€4,200 with no matching position change.
What was it?
```
```
[ Deposit ]        recon:pick:R80:deposit
[ Withdrawal ]     recon:pick:R80:withdraw   (shown when cash fell)
[ Dividend ]       recon:pick:R80:dividend
[ Something else ] recon:pick:R80:other
```
The result populates `Snapshot.external_flows` (owner-confirmed only when a delta is unexplained — MA-12), which feeds the time-weighted return math in D.4 so deposits never masquerade as alpha. `other` → ForceReply note.

All reconciliation prompts are answerable later (they persist as open asks in `/status`); they do not block snapshot acceptance — the snapshot is stored, the deltas are open loops.

### 3.5 Annual re-affirmation (A.1) — conviction / mgmt_trust / circle_fit

Ask-kind `F`, queued by the weekly review at a thesis anniversary (A.1). One prompted question per thesis, three fields, presented as a short sequence so each is one tap. Judgment anti-staleness: fundamentals refresh weekly, judgment refreshes yearly.

```
Annual re-affirmation — VEEV — F19 (thesis is 1 year old today)
Three judgments to re-affirm. Your answers only; I never set these (FR9).

1/3 — Conviction. You set this to HIGH a year ago. Still high?
```
```
[ Still high ]     reaff:set:F19:conviction:high
[ Change… ]        reaff:set:F19:conviction:change
```
`Change…` shows the enumerated set `[ high ] [ medium ] [ low ]` (conviction is enumerated — no free text). On answer, advance to 2/3:
```
2/3 — Management trust. You set: trusted_owner_operator. Still?
```
```
[ Unchanged ]      reaff:set:F19:mgmt:same
[ Change… ]        reaff:set:F19:mgmt:change
```
`Change…` → `[ trusted_owner_operator ] [ trusted_professional ] [ neutral ] [ distrust ]`. **Choosing `distrust` auto-opens an owner-initiated review** (A.2: post-activation downgrade to distrust auto-opens a review) — the bot states this consequence before recording: *"Marking distrust moves VEEV to under_review (your call, always allowed). Confirm?"* Then 3/3:
```
3/3 — Circle fit. You set: core (healthcare SaaS). Still core?
```
```
[ Unchanged ]      reaff:set:F19:circle:same
[ Change… ]        reaff:set:F19:circle:change   → [ core ] [ edge ]
```
Each of the three may carry an optional note via a final `[ Add a note ]` ForceReply. All three answers are journaled with the ask_id `F19`. **Unresolved re-affirmations surface via the standard escalation (B.3)** — skips are counted (unless paused, D.6) and a persistently-skipped re-affirmation escalates to the weekly headline, exactly like an unverifiable trigger.

### 3.6 Malformed-reply → one re-prompt → counted-unanswered (D.5)

The universal rule for every ask kind. Enforced by the pending-ask state machine (§4):

1. The owner sends a reply that does not match the ask's enumerated option set or (for a free-text ask) is empty/whitespace/exceeds a sane length → the bot **re-prompts exactly once**, restating the ask and its options plainly: *"I didn't get a usable answer for {ask_id}. It takes exactly: {options}. One more try, or leave it and I'll record it as unanswered."*
2. A second malformed/absent reply, or the deadline passing → the ask is marked **counted-unanswered**. Its consequence follows its kind: a pre-fire prompted question → the UNVERIFIABLE escalation (B.3.4); an alert → the `alert_ignored` path (B.3.3); a re-affirmation → the re-affirmation-skip escalation (A.1).
3. During pause mode, step 2's counters freeze (D.6) — a re-prompt may still be sent, but the "counted-unanswered" transition does not fire until resume.

The re-prompt is calm, never chiding. "Leave it and I'll record it as unanswered" makes non-response a first-class, recorded choice (FR8: ignoring is allowed, but recorded) — not a failure state.

### 3.7 Date-picker keyboard (for `/pause` custom end date)

A three-tap inline calendar (year already known): month row → day grid → confirm. Callback `pause:set:custom:<yyyy-mm-dd>`. Used only where a date is genuinely needed and enumerable. No ForceReply for dates.

### 3.8 Ticker-picker + pagination

Used by `/event` and any place the owner must choose among holdings. Buttons list held+backfill tickers, 8 per screen, with `[ ‹ Prev ]` / `[ Next › ]` rows (`page:nav:<context>:<n>`). A trailing `[ Not shown / new ]` row routes to the rare typed path. Pagination state is carried in callback_data, not server memory, so old buttons remain coherent.

### 3.9 Circle note (F.3, The Study) — optional free text

The weekly Study digest's circle-note line ("did anything expand or shrink the circle this week?") is **optional** (owner writes or skips; skipping is fine — F.3). Presented as `[ Add a circle note ]` on the Study message → ForceReply. Never chased, never escalated. This is the one free-text ask with zero consequence for silence.

### 3.10 Stale-button and double-tap handling

Every ask edits its own message on resolution (`editMessageText`) to strip the keyboard and show the recorded choice — so a resolved ask cannot be tapped again. If an *old* message's button is somehow tapped (owner scrolls up), the callback validation (§3.1) finds the ask already answered/expired and responds via `answerCallbackQuery`: *"Already recorded as {choice}"* or *"This ask is closed"* — no state change, no confusion. The `v<n>` grammar guard rejects buttons from an incompatible template version outright.

---

## 4. Free-text evidence capture — the pending-ask state machine

Free text is required in exactly these places, all consequential and all journaled against an ask-ID: **(a)** alert `refute` evidence (§3.3), **(b)** `can't-verify` note on a prompted question (§3.2), **(c)** reconciliation reasoning-at-the-moment for close/add/trim and the `other`/cash notes (§3.4), **(d)** optional re-affirmation notes (§3.5) and the optional circle note (§3.9), **(e)** the `Other` event note (§1.4) and the rare typed ticker/paste (§1.4/§1.5). Reliability requirement: **every free-text reply must journal against the exact ask that requested it** (D.5).

**Mechanism: ForceReply + reply-to correlation, backed by a server-side pending-ask state machine — belt and suspenders.**

1. **ForceReply** is used for every free-text ask. `sendMessage` carries `reply_markup: ForceReply(selective=true)` and its message text embeds the ask_id in a stable, parseable way (e.g. a trailing `[{ask_id}]` token). ForceReply focuses the owner's input box pre-quoting the prompt, so the owner's reply is a Telegram **reply-to** that message. On inbound, the bot reads `message.reply_to_message` and extracts the ask_id from it — the primary correlation path.
2. **Server-side pending-ask state machine** is the authoritative backstop, because ForceReply reply-to correlation can break (owner types a fresh message instead of replying; Telegram drops the reply linkage; owner answers out of order). SQLite holds the set of **open free-text asks** for the owner with their ask_ids, prompts, expected shapes, and deadlines. Rules:
   - When a free-text ask is opened, it is recorded as `pending_freetext` with its ask_id and a `sent_message_id`.
   - An inbound plain text message (not a command, not a callback) is resolved to an ask by: (i) `reply_to_message` ask_id if present and still open — authoritative; else (ii) if **exactly one** free-text ask is open, attribute to it; else (iii) if **multiple** are open and reply-to is absent, the bot **cannot guess** — it replies with a disambiguation keyboard listing the open asks by ask_id and short label (`[ Refute CRWD/T2 ]` `[ Note VEEV/T3 ]`), tap to bind the text to that ask. Guessing is never allowed for consequential evidence.
   - Once bound, the text is written verbatim to the journal with the ask_id and `inputs_ref`, the ask transitions to `answered`, and the pending record is cleared. The bot confirms: *"Recorded against {ask_id} (CRWD refute): '…'"* echoing the first ~60 chars so the owner sees it landed on the right ask.
   - The malformed/empty rule (§3.6) applies: empty or whitespace-only reply → one re-prompt → counted-unanswered.
3. **Only one free-text ask should normally be open at a time** by scheduling discipline (asks are queued and presented sequentially where possible), which makes path (ii) the common case and disambiguation rare. But the state machine correctly handles concurrency (an alert refute opened while a reconciliation note is pending) rather than assuming it away.
4. **No global "free chat" interpretation.** Any text that resolves to no open ask and is not a command is answered with the gentle-redirect fallback (§8) — never parsed as data, never stored. This is what keeps stray messages from ever corrupting the register.

This design satisfies the reliability requirement: the ask_id is the join key end to end (mint → button/ForceReply → SQLite pending record → journal entry → RunLog `inputs_ref`), and no free text is ever journaled without a confirmed ask binding.

---

## 5. Security & delivery

### 5.1 Owner chat-id allowlist — drop everything else silently

- The single allowlisted `chat_id` (and `user_id`) is **pre-provisioned at install time in the 0600 EnvironmentFile** (§1.1, amended — never bound in-chat). It is the *only* recipient the bot ever `sendMessage`s to and the *only* sender it ever processes.
- **Every inbound update** (message, callback, document, inline query, chat-member change) is checked against the allowlist as the very first middleware step. A non-matching update is **dropped silently** — no reply, no error, no "not authorized" message (a reply confirms the bot exists and is worth attacking). It is logged locally (RunLog / security log) with the offending id for the owner's audit, and nothing else happens.
- Group chats: the bot is designed for one private chat. If added to any group, it leaves immediately (or ignores all group updates) — group context does not exist in this design.
- `my_chat_member` updates (owner blocks/unblocks the bot) are handled: on block, delivery is marked blocked and outputs queue (§5.3); on unblock, the queue flushes oldest-first with an "delivered late" banner.

### 5.2 Bot token handling

- The bot token is a secret, read at process start from an environment variable or a `0600` file on the always-on Ubuntu box — **never** hardcoded, never in git, never in a report, never echoed in any message or log line (token is redacted in all logging).
- The box has no inbound ports and no public IP (owner-locked): the bot uses **Telegram long-polling** (`getUpdates`), not webhooks — no listening socket to attack. systemd runs the process with `Restart=always` so a crash or a reboot brings it back; `getUpdates` resumes from the last acknowledged update offset so nothing scheduled is lost across restarts.
- Data stays on the box (NFR2, invariant 8): SQLite + the git repo are local; no third-party analytics, no telemetry, no outbound calls except Telegram API and the adopted data stack.

### 5.3 Behavior when Telegram / network is down — alerts queued, never lost; letter marked late, never skipped

The scheduled runs (daily/weekly/quarterly/event) are decoupled from delivery. A run **always produces its output object and archives it (SQLite + git markdown) first**; delivery is a second step that can fail and retry without losing the artifact (NFR1, NFR4).

- **Outbound delivery queue:** every message the bot wants to send is enqueued with its artifact reference and a priority (alerts > daily letter > weekly > quarterly > Study). If Telegram is unreachable or the owner has blocked the bot, items **stay queued and are retried with backoff** — never dropped. Alerts specifically are **never lost**: an alert artifact is durable in SQLite the instant it is generated, independent of whether it has been delivered.
- **The daily letter is marked late, never skipped** (G.1, NFR1): if a daily run could not deliver on time, the letter is still generated and archived; when delivery resumes it is sent with a banner *"(delivered late — generated {t})"* and its staleness header already states the data age. The letter is never silently omitted (subject to `daily_letter_mode: quiet` during a declared pause, which is a deliberate owner choice, not a failure — D.6).
- **On reconnect / unblock:** the queue flushes oldest-first, alerts first within a timestamp. Superseded items are collapsed where honest (e.g. three days of undelivered daily letters send only the most recent as current, with a one-line note that N earlier letters are in the archive — the owner does not want a backlog of stale "no action needed" letters, but the archive keeps them all for NFR4).
- **Data-source failure** (yfinance/FX down) is orthogonal and already handled by the degraded-letter variants (§2.1) — the letter still sends and says "I just can't see."

### 5.4 Flood-limit awareness

- Telegram enforces ~1 msg/sec to a chat and ~20/min bursts. The bot's normal volume is one message per scheduled run, so limits are almost never hit — except the **weekly numbered series** (§2.2, ~4 messages + 1 document) and the **storm-expansion** case where the owner rapidly taps several alert items.
- The outbound queue (§5.3) is **rate-paced**: messages to the chat are spaced ≥1s; on a `429 Too Many Requests` the bot honors the `retry_after` value and re-enqueues — it never hammers. The weekly series sends sequentially with pacing, document first.
- Callback answers use `answerCallbackQuery` promptly (within Telegram's window) to clear the client's spinner even when the underlying action takes longer (the heavy work happens after the ack) — the owner never sees a hung button.
- **No unsolicited bursts by design:** the anti-complexity ledger already forbids intraday anything, streak counters, and news pings, so there is no code path that could flood the chat. Rate-limit safety is mostly a property of the design, backed by the paced queue as insurance.

---

## 6. Register and tone rules embedded structurally

These are not style guidance — they are enforced by the template layer and a pre-send lint (§8), so no message can violate them regardless of author.

### 6.1 Verbatim mandatory blocks

- **The WHAT-THIS-IS-NOT block (G.3)** is a fixed template fragment, reproduced verbatim in **every** alert (§2.5): *"WHAT THIS IS NOT: not a price alarm. The stock is {pct} this month; that is not why you are reading this and it plays no part in what follows. Cost basis is not shown and will not be considered."* — only `{pct}` is substituted; the sentence structure is immutable. An alert cannot be constructed without it.
- **The alert deadline framing** is fixed: *"decision by {date} ({n} days)"* in the header — never "URGENT", never "ACTION REQUIRED".
- **The invitation closer** is a fixed fragment on every opportunity/fair-entry line: *"this is an invitation, not an instruction."*
- **The degraded-data line** is fixed: *"Nothing is wrong; I just can't see."*
- **The indexing-exit clause (G.4 §7)** is fixed verbatim in the quarterly document.

### 6.2 Structural prohibitions (lint-enforced, §8)

- **No exclamation mark** may appear in any alert, prompted-question, reconciliation, or re-affirmation template. The lint rejects `!` in these output classes at send time.
- **No red-alarm glyphs** (🔴 🚨 ⚠️ ❗ ❌ as emphasis on state) in any scheduled output. The only sanctioned status glyph is `✓` for the calm/pass state. (`×`/`✗` may mark a *failed data check* in the data-health appendix, never a price or a thesis alarm.)
- **No euro cash amount, no portfolio value, no P/L, no cost basis** in the daily letter or `/status` — cash is band-% only (G global rules, FS-F8). The lint rejects a `€`-with-digits token in daily-letter output outside the (nonexistent) value field.
- **No benchmark / relative-performance token** in any daily, weekly, event, or alert output — the quarantine is an absent input (invariant 7). The lint rejects benchmark identifiers (`S&P`, `^SP500TR`, "vs index", "outperform") outside the quarterly document class.
- **No imperative mood** on actionable lines — advice verbs only ("consider", "you may", "the plan working"), never "buy", "sell now", "you must". Sell *advice* on a broken thesis is phrased as advice with cost basis explicitly disowned.
- **"No action needed" is the headline** — when the daily verdict is calm, that phrase is the bold first-line tail (`— ✓ No action needed`), structurally the most prominent text, never buried.

### 6.3 Calm-register defaults

- Sentences are declarative and short. Numbers are stated flatly. A price decline is reported as a plain fact and, in alerts, immediately disowned as irrelevant to the decision.
- The bot never congratulates the owner on gains, never uses "winning/losing", never compares to anyone else's return (envy rule, Naval). The one celebrated state is *doing nothing when nothing needs doing*.

---

## 7. State model summary (how an ask lives)

```
mint(ask)  →  open  ──(valid enumerated reply)──▶  answered  →  journaled(ask_id, inputs_ref)
   │            │
   │            ├──(malformed / empty)──▶ reprompted ──(2nd malformed / deadline)──▶ unanswered
   │            │                                                                        │
   │            └──(pause active)──▶ frozen (counters halted) ──(resume)──▶ open         ▼
   │                                                                        escalation per kind
   └── every ask carries: kind{A,Q,R,F} · enumerated options · thesis/trigger ref ·
       deadline · sent_message_id · state · (free-text asks also: pending_freetext record)
```
- **answered** always writes a JournalEntry (invariant 2, FR8) with the ask_id and `inputs_ref` RunLog pin.
- **unanswered** writes the appropriate auto-journal (`alert_ignored`) or escalation flag; ignoring is recorded, never silently dropped.
- **frozen** is the pause-mode state (D.6) — no counter advances, alerts still deliver.

---

## 8. Cross-cutting delivery rules (implementation-binding, not code)

- **One escaping discipline:** the formatting mode is `parse_mode=HTML`, locked (§2, amended); every dynamic field (tickers, multiples, owner free-text, notes) passes through the one `& < >` escaper before send. Owner free-text is the highest-risk field and is always escaped — echoing a refute back to the owner must not break rendering or inject formatting.
- **Pre-send lint:** every outgoing message passes a lint that enforces §6.2 (no `!` in the named classes, no red glyphs, no €-value in daily, no benchmark token outside quarterly, mandatory verbatim blocks present in alerts). A message failing lint is **not sent**; it raises an internal error and falls back to a safe minimal template, because shipping a register violation is worse than a terse message.
- **Idempotent delivery:** each artifact has a stable id; the delivery queue records delivered-artifact-ids so a retry after a partial failure never double-sends the same letter/alert.
- **`sendChatAction: typing`** precedes any action that takes more than ~1s (an `/event` check, a `/snapshot` parse) so the owner sees the bot is working; every owner action is acknowledged immediately (callback ack or a one-line "on it") even when the result follows.
- **Gentle-redirect fallback:** any inbound text that is not a command and resolves to no open ask (§4) gets one calm reply: *"I only act on the commands and on questions I've asked you. Nothing is waiting right now. /status shows the current picture."* — never parsed, never stored.

---

## 9. Traceability — this spec back to the binding sources

| Interface element | Source |
|---|---|
| Every ask = first-class object, stable ID, enumerated replies | D.5 owner interaction contract |
| Alert options {confirm broken / refute+evidence / revise-after-refute}; storm bundle by weight, one deadline | B.3.2, B.3.5, G.3 |
| Prompted trigger question {yes / no / can't-verify + note}; UNVERIFIABLE escalation | B.2 type-5, B.3.4, D.5 |
| Reconciliation prompts (appeared/disappeared/qty/cash) | E.1, MA-12 |
| Annual re-affirmation {conviction, mgmt_trust, circle_fit}; distrust auto-opens review | A.1, A.2 |
| Malformed → one re-prompt → counted-unanswered | D.5 |
| Daily letter layout, one-screen, degrades honestly, never skipped | G.1, FR4, NFR1 |
| Weekly review split (numbered series + sendDocument) | G.2 (exceeds 4096) |
| Quarterly report (document + summary), benchmark only here | G.4, FR13, invariant 7 |
| Event report quiet-line vs alert | D.3, FR6 |
| WHAT-THIS-IS-NOT verbatim; no `!`; no red typography; no daily €/value/P&L; invitation framing | G global rules, FS-F8 |
| `/pause` freezes all counters; `daily_letter_mode` | D.6, NAV-6/9 |
| `/event` owner as first-class sensor; filings owner-attested | D.3b, FR6 |
| `/snapshot` source-agnostic ingestion; reconciliation on every snapshot | E.1 |
| Owner chat-id allowlist, drop-silently, local-only | NFR2, invariant 8 |
| Alerts queued never lost; letter late never skipped | NFR1, NFR4 |
| Free-text journaled against its ask-ID | D.5, F.1, RunLog inputs_ref |
| No thesis/config editing via bot; desk-authored owner fields | FR9, invariant 1, C-series |

---

## 10. Out of scope (confirmed)

Gate prose authoring, Scout screen execution, and Study restudy writing are **desk rituals** (Claude Code / CLI at the always-on box, entering the system as owner-typed SQLite data). The bot never authors qualitative content and never runs an LLM. Its entire job in those flows is downstream: it collects the enumerated answers and the committed free-text fields defined above, journals them against their ask-IDs, and delivers the deterministic reports. Technology/runtime code structure, DB schema, and the CSV adapter internals are the next design step, not this spec.
