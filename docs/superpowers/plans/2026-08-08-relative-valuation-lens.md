# Relative Valuation Lens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish Scout's dated price and a conditional sector-relative owner-cash valuation signal on every Top 48 card and thesis reader.

**Architecture:** Extend the existing allowlisted reader projection in `stock-scout/webapp.py` with a deterministic valuation lens derived from the point-in-time detail and the full compact Scout universe. Render it in the existing static card and reader views, then add a blocking production gate so incomplete or misleading valuation context cannot be published.

**Tech Stack:** Python 3.13, pytest, existing static HTML/CSS/JavaScript generator, GitHub Pages, agent-browser.

---

## File map

- Modify `stock-scout/webapp.py`: valuation percentile helper, allowlisted reader fields, card and reader rendering.
- Modify `stock-scout/tests/test_webapp.py`: calculation, projection, privacy, and generated-interface tests.
- Modify `agentcy/production.py`: valuation-lens release gate.
- Modify `tests/test_production.py`: incomplete and valid snapshot gate cases.
- Modify `docs/runbook.md`: valuation semantics and fallback rules.

### Task 1: Define valuation semantics with failing tests

**Files:**
- Modify: `stock-scout/tests/test_webapp.py`
- Modify: `stock-scout/webapp.py`

- [ ] Add focused tests for midpoint tie percentiles, five signal boundaries, a sector cohort of at least 20, and full-universe fallback for a missing sector.
- [ ] Run `uv run pytest stock-scout/tests/test_webapp.py -k valuation_lens -v` and confirm failures are caused by the missing valuation helper.
- [ ] Implement `relative_percentile`, `valuation_signal`, and `public_valuation_lens` with finite-number validation, positive-yield multiple calculation, explicit comparison labels, and deterministic rounding.
- [ ] Re-run the focused tests and require PASS.
- [ ] Commit only the helper and its tests with `feat: derive relative owner-cash valuation context`.

### Task 2: Project the actual Scout quote

**Files:**
- Modify: `stock-scout/tests/test_webapp.py`
- Modify: `stock-scout/webapp.py`

- [ ] Add a failing projection test proving that `bundle["price"]` and `bundle["price_as_of"]` become `reader["valuation_lens"]`, while unrelated detail fields remain private.
- [ ] Run `uv run pytest stock-scout/tests/test_webapp.py -k 'reader and valuation' -v` and verify RED.
- [ ] Pass the full compact-row cohort into reader assembly, join the point-in-time `price` into the internal detail model, and attach exactly one allowlisted lens to every accepted reader.
- [ ] Re-run the focused tests and require PASS.
- [ ] Commit with `fix: expose dated Scout prices in thesis readers`.

### Task 3: Render cards and the full valuation panel

**Files:**
- Modify: `stock-scout/tests/test_webapp.py`
- Modify: `stock-scout/webapp.py`

- [ ] Add failing HTML contract tests for `Current price`, `Owner cash yield`, equivalent multiple, named comparison percentile, conditional caveat, and absence of buy/sell wording.
- [ ] Run `uv run pytest stock-scout/tests/test_webapp.py -k 'valuation and html' -v` and verify RED.
- [ ] Add the compact signal and dated price to every Top 48 card; add the five-part valuation context panel to the reader; keep quality, risk, and valuation in separate containers.
- [ ] Add responsive CSS so the panel is one column at 390px and introduces no horizontal overflow.
- [ ] Re-run `uv run pytest stock-scout/tests/test_webapp.py -v` and require PASS.
- [ ] Commit with `feat: render valuation lens on Top 48 cards and readers`.

### Task 4: Block incomplete production snapshots

**Files:**
- Modify: `tests/test_production.py`
- Modify: `agentcy/production.py`

- [ ] Add failing release-gate tests for a missing price, stale/missing date, non-positive yield, invalid percentile, missing comparison scope, and missing caveat; add one complete passing record.
- [ ] Run `uv run pytest tests/test_production.py -k valuation -v` and verify RED.
- [ ] Add a `top_reader_valuation_complete` check to the existing validation report and require it for publication.
- [ ] Re-run the focused tests and require PASS.
- [ ] Commit with `feat: gate publication on complete valuation context`.

### Task 5: Document, build, and verify the exact artifact

**Files:**
- Modify: `docs/runbook.md`
- Generated: production snapshot and `docs/` site artifact through the existing production command only.

- [ ] Document price provenance, owner-cash-yield interpretation, sector/universe fallback, and the absence of buy/sell advice.
- [ ] Run the focused webapp and production suites, then the full repository suite; require fresh terminal PASS output.
- [ ] Build the production artifact through the existing local-production command and require all release checks green plus 48/48 valuation lenses.
- [ ] Verify desktop and 390px browser flows: card price, direct thesis route, valuation panel, comparison copy, Back/Forward, and no horizontal overflow.
- [ ] Copy only the exact validated artifact into `main:/docs`, commit it, and report the commit, snapshot ID, test totals, and whether GitHub authentication is the only remaining live step.

## Self-review

- Spec coverage: price projection, relative valuation, fallback, caveat, UI separation, privacy, mobile behavior, and release blocking are each mapped to a task.
- Placeholder scan: no TBD, TODO, or unspecified implementation step remains.
- Type consistency: all UI and gate work consumes the single `valuation_lens` shape defined in the design.

