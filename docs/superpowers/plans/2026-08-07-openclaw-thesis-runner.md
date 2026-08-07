# OpenClaw Thesis Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and mechanically validate every changed top-1% draft with owner-approved `gpt-5.6-sol` before publishing GitHub Pages.

**Architecture:** Extend the existing injected local production adapter with a narrow external runner. Python prepares work orders, invokes the runner, validates artifacts through the existing Gate and blocks publication on any failed candidate.

**Tech Stack:** Python 3.13, pytest, Bash, OpenClaw CLI, SQLite.

---

### Task 1: Approve the model and add the runner contract

**Files:** `stock-scout/deskwork.py`, `stock-scout/tests/test_thesis_engine.py`, `deploy/local/scout-thesis-runner.sh`, `tests/test_production_deploy.py`

- [ ] Add a failing test that `gpt-5.6-sol` resolves as an approved OpenAI model.
- [ ] Add failing deploy tests for isolated session key, explicit model, max thinking and timeout.
- [ ] Implement the allowlist entry and narrow OpenClaw runner.
- [ ] Run focused tests and commit.

### Task 2: Execute changed work orders inside production

**Files:** `stock-scout/local_production.py`, `stock-scout/production.py`, `stock-scout/tests/test_local_production.py`, `deploy/local/scout-production.sh`, `deploy/local/scout-production.env.example`

- [ ] Add failing tests proving missing/changed drafts invoke the runner and accepted unchanged drafts are reused.
- [ ] Extend configuration with runner path and model ID.
- [ ] Prepare work orders in one batch, invoke each candidate runner and call `thesis.record`.
- [ ] Persist `FAILED` for any runner or validation failure and retain the existing release gate.
- [ ] Run focused tests and commit.

### Task 3: Generate, validate and publish

**Files:** generated local thesis state and `bot/site` public artifacts only.

- [ ] Run the complete local production job over 5,763 eligible securities.
- [ ] Execute all required top-1% work orders with max effort and resume safely.
- [ ] Verify every top member has an accepted record and no private public fields exist.
- [ ] Run the full test suite.
- [ ] Push main, publish the validated snapshot to `bot/site`, verify the live site and report exact counts.
