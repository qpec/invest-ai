# Backfill-Thesis Onboarding — Design

**Status:** approved-in-pieces 2026-07-11. Realizes the owner goal: existing (eToro) holdings each get a thesis that ORIGINATES from the invested moment, so the Watchdog monitors it and advises when the thesis breaks. Complements the deferred `origin='backfill'` thesis type the schema already anticipates. The Gate (deliberate buy-discipline for NEW buys) is unchanged; this is the distinct "onboard a holding I already own" path.

## Problem

The Watchdog only monitors positions that have a live thesis (`weekly.py` skips thesis-less holdings). Theses are created only through the interactive Gate. So ingested eToro positions sit unmonitored. The invested-moment data (`position_detail.opened_at`, entry price, invested amount) is already captured but never used to originate a thesis.

## Flow (per held position without a live thesis)

1. **Detect** — after a snapshot ingest, find held positions (non-cash) with no `register.live_thesis_for(ticker)`.
2. **Baseline** — compute the fundamentals baseline from the append-only archive as of the invested moment / latest available (revenue YoY, owner-FCF margin, net debt/EBITDA, shares YoY) — the business's state that anchors the thesis.
3. **Auto-derive the four deterministic invalidation triggers** (Moderate defaults, each relative to the baseline; owner edits per name at ratification):
   - **growth_floor** — `revenue_yoy > baseline_revenue_yoy - 10pp`
   - **margin_erosion** — `owner_fcf_margin > baseline_margin x 0.75` (not > 25% below)
   - **balance_sheet_safety** — `net_debt/EBITDA < min(baseline_ndte + 1.0, 4.0)`
   - **dilution** — `shares_yoy < 5%/yr`
   (`owner_attested_event` is not auto-derived; the owner may add one at ratification.)
4. **Claude drafts the qualitative thesis** (via claudeclaw / the desk — shared with Stage-2 Part B): from the fundamentals + latest filings + the invested moment, Claude drafts the NOT-NULL thesis fields — `business_model_2s`, `moat_types` + `moat_evidence`, `owner_earnings_json/narrative`, `fair_band`, `conviction`, `mgmt_trust`, `circle_fit`, `ten_year_statement`. `value_at_purchase` is filled from the invested moment (entry = `invested_eur / quantity`) — **record-keeping only; quarantined from advice** (the invalidation triggers fire on the BUSINESS deteriorating, never on price-vs-entry: "the stock doesn't know what you paid").
5. **Owner ratifies via Telegram** — the draft is delivered as a ratification **ask**; the owner taps **approve** (thesis -> `intact`, monitored) or **replies edits** (conviction / triggers / rationale). It stays `draft` and UNmonitored until approved. Never faked, never auto-live (FR9 / owner-judgment principle).
6. **Watchdog monitors** (already built) — weekly it tests the armed triggers, fires an alert + decision-ask on a break (`thesis -> under_review`), and reports each holding against its thesis in the letter.

## Architecture (two layers, mirrors Stage-2)

- **agentcy (Python, in-repo, built + tested now):** the deterministic scaffolding — detection of thesis-less holdings, the baseline + Moderate trigger auto-derivation, the `origin='backfill'` thesis record (draft) anchored to the invested moment, and the Telegram ratification ask (approve/edit -> `intact`). Exposed as a job/CLI: `agentcy thesis backfill [--ticker T]` (emits drafts + asks), reusing `register.create_thesis`, `triggers`, `asks`, and the daemon's ask-handling. Testable offline with seeded positions + fundamentals.
- **claudeclaw (Part B, on the droplet):** drafts the qualitative fields for each backfill dossier. Shares the Stage-2 claudeclaw harness (the same owner-subscription-on-box setup). Until claudeclaw is set, the deterministic scaffolding + triggers still work; the qualitative draft can be filled at the desk via `agentcy gate` backfill mode.

## Error handling
- Thin/stale fundamentals -> the affected trigger is emitted as `BOOTSTRAPPING` / the baseline leg is skipped, never faked; the thesis can still onboard with the computable triggers, flagged.
- A holding that is cash / an ETF / outside-framework -> no thesis (existing behaviour); reported as "outside framework", not onboarded.
- Owner never approves -> the thesis stays `draft`, unmonitored; the holding is reported as "awaiting thesis ratification" in the letter (not silently skipped).

## Testing (agentcy layer, offline)
- Detection of thesis-less holdings; the four Moderate trigger derivations from a seeded baseline (exact thresholds); the backfill thesis record (origin, anchor, value_at_purchase from entry, triggers armed on ratify); the ratification ask round-trip (approve -> intact + monitored; edit -> stays draft); cost-basis stays out of `positions_advice`; a broken-trigger fires an alert on the backfilled thesis via the existing Watchdog. All offline (seeded positions + fundamentals).

## Scope (YAGNI)
**In:** the agentcy backfill scaffolding (detection + baseline + Moderate triggers + backfill thesis + Telegram ratification ask) and its wiring to the Watchdog.
**Not in this build:** the claudeclaw qualitative-drafting harness (Stage-2 Part B, shared, needs the owner's subscription on the box); the live eToro API wiring (Track 1, needs the owner's API key); any price-vs-entry trigger (cost basis stays quarantined); any change to the Gate's new-buy discipline.
