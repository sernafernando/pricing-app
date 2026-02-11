---
name: pricing-app-testing-ci
description: Testing and CI minimums for backend, frontend, and critical business flows
license: MIT
metadata:
  author: pricing-app
  version: "1.0.0"
  scope: [root, backend, frontend]
  auto_invoke:
    - "Adding new backend endpoint behavior"
    - "Refactoring auth or pricing logic"
    - "Changing frontend critical user flows"
    - "Setting up or modifying CI pipelines"
    - "Fixing production bugs that require regression tests"
allowed-tools: Read, Edit, Write, Glob, Grep, Bash
---

# Pricing App Testing + CI

## Trigger

Use this skill when adding/changing behavior and when touching CI.

## Baseline Testing Strategy

Priority order:

1. Backend integration tests for auth/pricing/sync.
2. Backend unit tests for pricing and permissions logic.
3. Frontend integration tests for login and critical interactions.
4. E2E smoke for top business flows.

## Required Minimum by Change Type

### New behavior

- Add at least one automated test covering the new behavior.

### Bug fix

- Add regression test that reproduces the old failure and now passes.

### Critical path change (auth/pricing/sync)

- Must include happy path and failure path tests.
- Must run in CI for pull requests.

## CI Guardrails

- CI must run on pull requests.
- Merges must be blocked when required checks fail.
- Keep checks focused on touched areas to reduce runtime.

## Practical Checklist

- Does this change alter behavior? If yes, add tests.
- Are failure paths tested (`401/403/422/500` as relevant)?
- Did we run backend/frontend checks relevant to changed files?
- Is there a regression test for known incident fixes?

## PR Output Contract

Include in PR summary:

- Exact commands executed.
- Pass/fail status for each command.
- Known test gaps and follow-up ticket (if any).

## Anti-Patterns

- Refactors with no tests in critical modules.
- CI that only lints but does not execute tests.
- Massive end-to-end suites for trivial changes.
- Flaky tests with no deterministic fixture strategy.

## References

- `AGENTS.md`
- `TECH_BACKLOG_30_60_90.md`
- `backend/CLAUDE.md`
- `frontend/CLAUDE.md`
