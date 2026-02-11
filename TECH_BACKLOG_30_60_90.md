# Technical Backlog 30/60/90 - Pricing App

Last update: 2026-02-10
Owner: Engineering Team

## Context and Goal

This backlog turns the health-check into executable work. The goal is to reduce operational risk, improve delivery speed, and stabilize critical flows (auth, pricing updates, sync jobs).

## Current Snapshot (verified)

- Backend routes are large in scope (`~357` route decorators in `backend/app/api/endpoints`).
- Backend codebase is substantial (`~269` Python files under `backend/app`).
- Error handling is broad in many places (`~267` `except Exception` matches in `backend/app`).
- Frontend has broad surface area (`~67` JSX files in `frontend/src`).
- CI workflows are not present (`.github/workflows/*` not found).
- Documentation quality is uneven (`README.md` is strong; `frontend/README.md` remains template-level).

## Priority Framework

- P0: Security and production safety.
- P1: Delivery reliability and regression prevention.
- P2: Maintainability and observability.

Effort scale: S (1-2 days), M (3-5 days), L (1-2 weeks).

---

## 30 Days (Stabilize Fundamentals)

### T01 - Add baseline CI pipeline (lint + smoke)
- Priority: P0
- Effort: M
- Scope:
  - Add GitHub Actions for backend and frontend lint checks.
  - Add backend smoke tests for startup and health endpoint.
  - Add required status checks for protected branches.
- Acceptance criteria:
  - Pull requests run CI automatically.
  - Main branch cannot merge on red checks.

### T02 - Lock down CORS by environment
- Priority: P0
- Effort: S
- Scope:
  - Replace wildcard CORS in `backend/app/main.py` with env-based allowed origins.
  - Keep permissive defaults only for local development.
- Acceptance criteria:
  - Production config has explicit trusted origins.
  - No `allow_origins=["*"]` in production path.

### T03 - Define and test critical backend flows
- Priority: P0
- Effort: M
- Scope:
  - Add automated tests for:
    - Login + token refresh (`auth`).
    - Product price update endpoint.
    - One ML sync entrypoint.
- Acceptance criteria:
  - At least 3 critical flow tests run in CI.
  - Failing behavior blocks merge.

### T04 - Standardize error responses for core endpoints
- Priority: P1
- Effort: M
- Scope:
  - Define shared error response contract.
  - Apply first to auth, pricing, and sync endpoints.
- Acceptance criteria:
  - Error payload format is consistent for selected endpoints.
  - API docs include error response examples.

### T05 - Replace `print` with structured logging in app lifecycle
- Priority: P1
- Effort: S
- Scope:
  - Replace startup/background `print` calls in `backend/app/main.py` with logger.
  - Add log levels and contextual fields.
- Acceptance criteria:
  - Startup/shutdown/background logs appear with level and timestamp.

---

## 60 Days (Consolidate Architecture)

### T06 - Decide migration source of truth (Alembic-first)
- Priority: P0
- Effort: M
- Scope:
  - Publish a DB migration policy.
  - Mark legacy folders (`backend/migrations`, `backend/db_migrations`, `backend/sql`) as read-only or archived when possible.
  - Define process for all new schema changes via Alembic.
- Acceptance criteria:
  - Documented migration policy in repo.
  - Team follows one standard for new DB changes.

### T07 - Reduce broad exception handlers in critical modules
- Priority: P1
- Effort: L
- Scope:
  - Refactor top 20 most critical `except Exception` occurrences.
  - Use specific exceptions and actionable error logging.
- Acceptance criteria:
  - Critical modules show specific exception handling.
  - Error logs include actionable context.

### T08 - Introduce backend test structure and fixtures
- Priority: P1
- Effort: M
- Scope:
  - Create canonical test layout (`tests/unit`, `tests/integration`, shared fixtures).
  - Add db/session fixtures and API client fixture.
- Acceptance criteria:
  - New tests follow standard structure.
  - Fixture reuse reduces duplicated setup.

### T09 - Add frontend integration test baseline
- Priority: P1
- Effort: M
- Scope:
  - Add 3-5 UI integration tests for login, route guard, and a pricing interaction.
  - Include them in CI.
- Acceptance criteria:
  - Frontend has automated regression coverage for critical UX.

### T10 - Refresh frontend documentation
- Priority: P2
- Effort: S
- Scope:
  - Replace template content in `frontend/README.md` with real setup, architecture, scripts, and troubleshooting.
- Acceptance criteria:
  - Frontend README is project-specific and onboarding-ready.

---

## 90 Days (Scale and Operate)

### T11 - Modularize API bootstrap (`main.py`)
- Priority: P1
- Effort: M
- Scope:
  - Split router registration, middleware setup, and startup tasks into dedicated modules.
  - Keep `main.py` as composition root only.
- Acceptance criteria:
  - `backend/app/main.py` is significantly slimmer and easier to review.

### T12 - Add correlation IDs and request tracing basics
- Priority: P1
- Effort: M
- Scope:
  - Inject request ID middleware.
  - Propagate request IDs through logs.
- Acceptance criteria:
  - A single request can be traced across logs.

### T13 - Define SLOs and alert thresholds
- Priority: P1
- Effort: M
- Scope:
  - Set SLOs for API p95 latency, error rate, and sync freshness.
  - Create alert policy and ownership.
- Acceptance criteria:
  - SLO document exists and is reviewed.
  - Alerts map to clear responders.

### T14 - Add API contract checks for high-impact endpoints
- Priority: P2
- Effort: M
- Scope:
  - Freeze response contracts for auth/pricing/sync endpoints.
  - Add contract tests to catch breaking changes.
- Acceptance criteria:
  - Contract-breaking changes fail CI.

### T15 - Delivery governance and quality gates
- Priority: P2
- Effort: S
- Scope:
  - Add PR template requiring test evidence and risk notes.
  - Add release checklist for migrations, rollback, and monitoring.
- Acceptance criteria:
  - All PRs use standardized quality checklist.

### T16 - Secrets scanning guardrails
- Priority: P0
- Effort: S
- Scope:
  - Add automated secret scanning in CI for pull requests.
  - Add local pre-commit hook guidance for secret detection.
  - Document false-positive handling process.
- Acceptance criteria:
  - PRs fail when potential secrets are detected.
  - Team has a documented local check command before commit.

### T17 - Branch protection baseline
- Priority: P0
- Effort: S
- Scope:
  - Enforce required checks for default branch.
  - Require at least one approval review.
  - Block merge on unresolved conversations and conflicts.
- Acceptance criteria:
  - Default branch cannot merge without passing checks + review.
  - Protection settings are documented in repo docs.

### T18 - CODEOWNERS for critical paths
- Priority: P1
- Effort: S
- Scope:
  - Add `CODEOWNERS` for auth, core backend, and shared frontend services.
  - Define fallback owner for cross-cutting files.
- Acceptance criteria:
  - PRs touching critical paths request owner review automatically.
  - Ownership map is visible and current.

### T19 - Operational runbooks (incident-first)
- Priority: P1
- Effort: M
- Scope:
  - Create runbook: "API degraded/down" with diagnosis and mitigation steps.
  - Create runbook: "ML sync delayed/stuck" with backlog recovery actions.
  - Include log sources, key queries, and rollback-safe actions.
- Acceptance criteria:
  - On-call can execute first response in < 15 minutes using docs only.
  - Runbooks include clear escalation owner.

### T20 - ADR baseline for core decisions
- Priority: P1
- Effort: S
- Scope:
  - Add 3 ADRs:
    - CORS strategy by environment.
    - DB migration source of truth.
    - Test strategy (critical flows + CI gates).
  - Define ADR template for future architecture decisions.
- Acceptance criteria:
  - ADR documents are versioned and linked from root docs.
  - Team references ADRs during PR reviews for aligned decisions.

---

## Suggested Execution Order

1. T01 -> T02 -> T03 -> T05
2. T06 -> T08 -> T07 -> T09
3. T11 -> T12 -> T13 -> T14 -> T15
4. T16 -> T17 -> T18 -> T19 -> T20

## Tracking Template (copy per ticket)

```
Ticket: TXX
Owner:
Status: todo | in_progress | blocked | done
Risk:
PR:
Notes:
```

---

## AI-Focused Kanban Board

This board is optimized for AI agents. Each card has explicit scope, constraints, and machine-checkable done criteria.

### To Do

#### T01 - Baseline CI pipeline
- Goal: create minimal CI for backend/frontend quality gates.
- AI input prompt:
  - "Create `.github/workflows/ci.yml` with backend lint + smoke and frontend lint. Keep jobs independent and fail fast."
- Files expected:
  - `.github/workflows/ci.yml`
  - Optional: `backend/tests/smoke/test_health.py`
- Done when:
  - Workflow triggers on `pull_request`.
  - Backend lint and frontend lint both run.
  - Health endpoint smoke test runs.

#### T02 - CORS hardening
- Goal: remove wildcard CORS in production path.
- AI input prompt:
  - "Refactor CORS config in `backend/app/main.py` to use environment-based allowed origins from settings."
- Files expected:
  - `backend/app/main.py`
  - `backend/app/core/config.py`
  - `backend/.env.example`
- Done when:
  - No `allow_origins=["*"]` in production branch.
  - Origins configurable via environment variable.

#### T03 - Critical flow tests
- Goal: lock high-risk regressions with automated tests.
- AI input prompt:
  - "Add integration tests for login, token refresh, one pricing update endpoint, and one ML sync endpoint."
- Files expected:
  - `backend/tests/integration/test_auth_flows.py`
  - `backend/tests/integration/test_pricing_flow.py`
  - `backend/tests/integration/test_sync_ml_flow.py`
- Done when:
  - At least 3 critical tests pass in CI.
  - Tests fail on auth/pricing/sync regressions.

### In Progress

#### T05 - Structured lifecycle logging
- Goal: replace startup/background `print` statements with structured logger.
- AI input prompt:
  - "Replace print-based logs in app startup/background tasks with Python logging using levels and consistent message format."
- Files expected:
  - `backend/app/main.py`
- Done when:
  - No raw `print` in startup/shutdown/background task path.
  - Logs include level and timestamp.

### Next Up

#### T06 - Migration policy unification (Alembic-first)
- Goal: define single source of truth for DB schema changes.
- AI input prompt:
  - "Create migration policy doc. Mark legacy SQL folders as legacy and define Alembic-only flow for new changes."
- Files expected:
  - `backend/MIGRATION_POLICY.md` (new)
  - `README.md` (link policy)
- Done when:
  - Policy is documented and referenced from root docs.
  - New schema process is explicit and enforceable.

#### T08 - Test architecture baseline
- Goal: standardize backend test layout and fixtures.
- AI input prompt:
  - "Create canonical backend test structure with shared db/session/client fixtures and docs for usage."
- Files expected:
  - `backend/tests/conftest.py`
  - `backend/tests/README.md`
  - `backend/tests/unit/` and `backend/tests/integration/`
- Done when:
  - New tests can reuse fixtures without custom bootstrap.
  - Directory structure is documented.

#### T16 - Secrets scanning guardrails
- Goal: block credential leaks before merge.
- AI input prompt:
  - "Add CI secret scanning for pull requests and document local pre-commit secret scan workflow."
- Files expected:
  - `.github/workflows/secrets.yml` or integrated CI job
  - `CONTRIBUTING.md` (local scan steps)
- Done when:
  - Secret detection runs on PRs and fails on high-confidence leaks.

#### T17 - Branch protection baseline
- Goal: enforce minimum merge safety.
- AI input prompt:
  - "Document and apply branch protection baseline requiring CI checks and one approving review."
- Files expected:
  - `docs/BRANCH_PROTECTION.md` (or `BRANCHING.md` update)
- Done when:
  - Required checks and review policy are documented and active.

#### T18 - CODEOWNERS for critical paths
- Goal: guarantee domain review on high-risk changes.
- AI input prompt:
  - "Create CODEOWNERS for backend core/auth and frontend shared service paths with fallback owners."
- Files expected:
  - `.github/CODEOWNERS`
- Done when:
  - Owner review requests trigger automatically on touched critical paths.

### Done

- Initial health-check completed.
- 30/60/90 backlog documented in this file.

---

## AI Execution Protocol (for each card)

Use this sequence to avoid noisy changes and broken PRs:

1. Read target files and local rules (`CLAUDE.md`, component `AGENTS.md`).
2. Produce minimal diff for one ticket only.
3. Run only relevant checks (lint/test for touched area).
4. Return evidence: changed files + check outputs + residual risks.

### PR Output Contract (AI must include)

- Scope: what was changed and what was intentionally not changed.
- Validation: exact commands executed and result.
- Risk notes: known limitations or follow-up items.
- Rollback: quick revert strategy.

### Suggested labels for AI-generated PRs

- `area:backend`, `area:frontend`, `area:devx`
- `priority:P0|P1|P2`
- `effort:S|M|L`
- `source:ai-assisted`

---

## JWT Refactor Test Matrix (Simple and Actionable)

Use this matrix to validate the JWT + refresh refactor and prevent regressions.

### P0 - Must have now

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| JWT-01 | Login success | Valid user + password | `POST /api/auth/login` | `200`, returns `access_token`, `refresh_token`, `token_type=bearer` |
| JWT-02 | Login invalid password | Valid user + wrong password | `POST /api/auth/login` | `401` |
| JWT-03 | Access token on protected endpoint | Valid access token | `GET /api/auth/me` | `200`, returns current user |
| JWT-04 | Missing token on protected endpoint | No token | `GET /api/auth/me` | `401` |
| JWT-05 | Refresh success | Valid refresh token | `POST /api/auth/refresh` | `200`, returns new `access_token` |
| JWT-06 | Refresh expired/invalid token | Expired or tampered refresh | `POST /api/auth/refresh` | `401` |
| JWT-07 | Wrong token type for refresh | Valid access token used as refresh | `POST /api/auth/refresh` | `401` |
| JWT-08 | Disabled user cannot refresh | User disabled after token issued | `POST /api/auth/refresh` | `401` |

### P1 - Strongly recommended next

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| JWT-09 | Access expiration enforced | Expired access token | `GET /api/auth/me` | `401` |
| JWT-10 | Refresh lifetime longer than access | Configured expirations | Issue both tokens | Refresh remains valid after access expiry window |
| JWT-11 | Protected endpoints are not open | Critical endpoints list | Call without token | All return `401`/`403` (never `200`) |
| JWT-12 | Permissions still enforced | Valid auth but missing role/permission | Call sensitive endpoint | `403` |

### P2 - Contract and safety net

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| JWT-13 | Auth contract stability (`/auth/login`) | Valid login request | `POST /api/auth/login` | Response shape remains stable |
| JWT-14 | Auth contract stability (`/auth/refresh`) | Valid refresh request | `POST /api/auth/refresh` | Response shape remains stable |
| JWT-15 | CORS + auth compatibility | Browser preflight + auth header | Call protected endpoint from allowed origin | Preflight and request succeed |

### Minimal execution plan (solo-dev friendly)

1. Implement and automate JWT-01 to JWT-08 first.
2. Add JWT-11 and JWT-12 as security regression guardrails.
3. Add JWT-13 and JWT-14 once CI is stable.

### Definition of done for this refactor

- All P0 cases passing in CI.
- At least one protected endpoint suite validating `401` without token.
- Refresh flow validated for both success and token-type failure.
