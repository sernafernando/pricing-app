# ADR-003 - Testing Strategy for Critical Flows

Status: Accepted
Date: 2026-02-10

## Context

The system has high business impact areas (auth, pricing, sync). Regressions there are expensive and often production-facing.

## Decision

- Critical flow changes must include automated tests.
- Minimum pattern: happy path + failure path.
- CI must execute required checks on pull requests and block merge on failures.
- Priority test stack:
  1. Backend integration for auth/pricing/sync.
  2. Backend unit for pricing/permissions logic.
  3. Frontend integration for login and critical interactions.

## Consequences

- Fewer production regressions in core workflows.
- Slightly longer PR cycle for critical changes.

## Follow-up

- Create baseline CI workflow.
- Add JWT regression suite and critical endpoint auth coverage.
