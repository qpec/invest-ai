# OpenClaw Thesis Runner Design

## Decision

The owner approves `gpt-5.6-sol` as the best-available OpenAI model for Scout
thesis research. The local production orchestrator may use the configured
OpenClaw OAuth route to execute top-1% thesis work orders.

## Runtime boundary

Python remains authoritative. It prepares one immutable work order per current
top-1% candidate and invokes a narrow runner executable with the symbol and
absolute work-order path. The runner starts an isolated Nova session using
`openai/gpt-5.6-sol` through the Codex harness with an explicit maximum-effort
instruction. The OpenClaw adapter reports this harness as fixed `thinking=off`, so
the runner deliberately does not send the unsupported `--thinking max` override.
Nova may write only the requested
draft artifacts. Python then calls the existing `thesis.record` validation and
persists `CREATED`, `REFRESHED`, `REUSED` or `FAILED` with the input fingerprint.

The runner never ratifies a thesis. Conviction, circle of competence and the
portfolio Gate remain owner-only.

## Failure and publication

Every top member must have an accepted draft. Missing files, invalid schemas,
unapproved model identity, runner timeouts and research failures become a
`FAILED` thesis evaluation. `thesis_evaluations_passed` then blocks snapshot
promotion and leaves the previous GitHub Pages version live.

## Operational contract

- Model: `openai/gpt-5.6-sol`, recorded as `gpt-5.6-sol`.
- Thinking: `max`.
- Session isolation: one deterministic session key per production run and symbol.
- Timeout: 60 minutes per symbol.
- Resumption: accepted drafts with unchanged fingerprints are reused.
- Publication: only after all top members pass mechanical validation.

## Verification

Tests prove the approved-model rule, runner invocation, accepted-draft reuse,
failure blocking and deploy configuration. A real run must produce an accepted
record for every current top-1% member before `bot/site` is updated.
