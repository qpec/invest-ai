# Scout Stage-2 — Qualitative Reviewer (claudeclaw-automated), Design

**Status:** approved 2026-07-11. Realizes the Scout v2 design §4 / §8 item 3 (the deferred LLM shortlist review). Ships as Scout v2.1. Does NOT change Stage-1 grading.

## Purpose

Stage-1 grades the whole US+EU universe deterministically on the measurable half of the Constitution. The philosophy-fidelity audit named the qualitative half it cannot reach — **moat durability / the 10-year test (Buffett), management candor & capital allocation (Munger), fads-vs-trends (Munger lollapalooza), circle/tier judgment (Naval)**. Stage-2 supplies exactly that, on a small shortlist only, with a bounded, reason-printed, never-silent adjustment. **The Scout still only surfaces; the Gate still decides.**

Chosen automation: **claudeclaw** (`moazbuilds/claudeclaw`, a Claude Code plugin/daemon) drives the review using the owner's Claude Code subscription — no Anthropic API key, no new agentcy dependency. It runs on the droplet; the scheduled agentcy runtime stays LLM-free (systemd timers never invoke `claude`). Human-triggered only (FR14): the owner messages claudeclaw; there is no cron auto-run (a weekly auto-emailed A-list is exactly the FOMO/action-bias Pillar 2 exists to suppress).

## Part A — agentcy Stage-2 CLI (Python, in-repo, built/tested/deployed like Stage-1)

- **`QualitativeReviewer` interface** with a `DeskReviewer` adapter (v1). The adapter's input is the recorded verdicts; the API adapter is a future slot behind the same interface. No LLM code, no new pip dependency.
- **`agentcy scout shortlist`** — runs the cached Stage-1 grade, selects the shortlist (**top 10 per tier + any Outside-tier A ≈ 30 names**, VETOED/INSUFFICIENT excluded), and emits a **review dossier**: per name, the deterministic grade + pillar scores + tier, the four questions, and doc pointers ("read the latest 10-K MD&A + business description + earnings-call transcript"). No numbers beyond the grade context — the deterministic layer owns all math.
- **`agentcy scout badge <ticker> --moat {confirmed|not-evident} --mgmt {aligned|neutral|red-flag} --fad {clear|flag} --tier {ok|correction:<T>} --reason "..."`** — records one name's verdicts into a review artifact (a dedicated `scout_shortlist_verdict` table, an explicit review artifact — NOT a monitoring table; results are human-read, never persisted as monitoring state). Any omitted axis is `pending` (never faked, FR9).
- **Bounded one-band adjustment** (deterministic, from the badges): a ⛔ fad-flag OR a management red-flag demotes one grade band; ✓ moat-confirmed + aligned + clear + tier-ok promotes one band **only if no pillar < 50**; otherwise unchanged. Always reason-printed. The reviewer **never** moves the composite number (math stays deterministic + auditable).
- **`agentcy scout review render`** — the annotated shortlist: deterministic grade → badges → one-band-adjusted final + reasons + the honest-evidence note. Rendered to the markdown archive repo. **Never written as monitoring state.** A name with no verdicts renders with its deterministic grade unchanged and "qualitative: pending".

## Part B — claudeclaw on the droplet (the automation harness)

- Install `claude` (Claude Code CLI) + `moazbuilds/claudeclaw` on the droplet, authed to the owner's Claude Code subscription (`claude plugin marketplace add moazbuilds/claudeclaw` → `claude plugin install claudeclaw` → `/claudeclaw:start`). Runtime is Node/Bun, entirely outside the agentcy Python venv — agentcy stays dependency-clean (NFR7).
- Author a **`scout-review` skill** (a markdown skill in the claudeclaw skills folder) whose prompt IS the Buffett/Munger/Naval rubric. On trigger, the Claude session:
  1. runs `sudo -u agentcy env AGENTCY_STATE_DIR=/var/lib/stock-agentcy agentcy scout shortlist` and parses the dossier;
  2. for each shortlisted name, reads its latest 10-K MD&A / annual report / earnings-call transcript from the web (no numbers — prose only);
  3. answers the four Constitution-grounded questions, citing evidence;
  4. records each via `agentcy scout badge ...`;
  5. runs `agentcy scout review render` and delivers the annotated shortlist to the owner.
- **Trigger:** the owner messages claudeclaw ("run the scout qualitative review"). **Human-triggered, never cron.**
- **Channel coexistence:** the box already runs the `agentcy-bot` Telegram daemon on the owner's bot token; claudeclaw uses a **separate bot/channel** (its own Telegram bot or Discord) so the two never collide.

## The four questions (Constitution-grounded)

1. **Moat + 10-year test (Buffett).** Is there a durable competitive advantage (network effects / switching costs / cost advantage / brand-trust / regulatory), and would it plausibly survive a decade? → `moat: confirmed` (name the moat) / `not-evident` (name the disruption risk).
2. **Management (Munger — skin in the game, candor, capital allocation).** Owner-operator alignment, candid capital-allocation reasoning, no promotional/evasive tone or related-party red flags? → `mgmt: aligned / neutral / red-flag`.
3. **Fad-vs-trend (Munger — lollapalooza).** A durable trend or a fad dressed as one (esp. "AI-branded" vehicles)? → `fad: clear / flag`.
4. **Tier / circle (Naval — the expanding edge).** Is the deterministic Core/Adjacent/Outside tier right given what the business actually does? → `tier: ok / correction:<Core|Adjacent|Outside>`.

## Error handling
- Missing/unavailable docs or genuine uncertainty → that axis stays `pending`; no adjustment for it; rendered honestly. Never fabricate a verdict (FR9).
- claudeclaw / claude unavailable → Stage-1 grades remain fully usable on their own; Stage-2 is purely additive.

## Testing
- **Part A (offline, in-repo):** shortlist selection (top-10-per-tier + Outside-A, exclusions); the badge→adjustment truth table (demote / promote-gated-by-no-pillar-<50 / unchanged / pending combinations); verdict round-trip through the review artifact; the annotated render + golden; asserts NO monitoring-table write and NO new pip dependency / LLM import in agentcy.
- **Part B:** validated by a real owner-triggered review run on the box (a live shakedown, like the initial deploy).

## Scope (YAGNI)
**In:** Part A (interface + DeskReviewer + shortlist + badge + bounded adjustment + annotated render + review artifact) and Part B (claudeclaw install + the scout-review skill + human trigger + separate channel).
**Not in:** the hand-rolled Anthropic API adapter (future slot behind the interface); any cron/auto-scheduled review (FR14); any persisted monitoring state from Stage-2; automated persisted doc storage (the reviewer reads at review time); any change to Stage-1 grading.
