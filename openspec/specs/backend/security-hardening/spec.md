# Spec: backend/security-hardening

**Capability**: `backend/security-hardening`
**Status**: Active (canonical source of truth)
**Origen**: Sincronizado desde `openspec/changes/archive/2026-07-03-security-quick-wins/specs/backend/security-hardening/spec.md`
**Última actualización**: 2026-07-16 (Requirement 3 reversed — see below)

> Backend security hardening: June 2026 audit quick wins (week 1). Four low-risk, high-value fixes: python-multipart CVE-2024-24762 remediation, OpenAPI docs env-gating, wipe-compras endpoint hardening, and login brute-force rate limiting (10/minute per IP, fail-open on Redis outage, Cloudflare-IP-keyed).
>
> **Requirement 3 was reversed on 2026-07-16.** The wipe-compras env-gate shipped
> here contradicted a prior recorded decision (2026-06-10) that accepted audit
> finding A-5 as a conscious risk. The endpoint is intentionally reachable in
> production, guarded by a dedicated critical permission, until the compras module
> is complete. The other three requirements stand unchanged.

---

## Requirement 1 — `python-multipart` CVE Remediation

The backend MUST depend on a `python-multipart` version that is not affected
by CVE-2024-24762, without altering any existing upload behavior.

### Scenario: Dependency version is patched

- **Given** `backend/requirements.txt`
- **When** the dependency list is inspected
- **Then** `python-multipart` is pinned to `>=0.0.20,<0.1`

### Scenario: Existing upload flows keep working

- **Given** the `python-multipart` version bump has been applied
- **When** the existing backend test suite covering upload/attachment
  endpoints is run (etiquetas ZPL/upload/colecta, compras adjuntos, caja,
  RRHH, tickets, sounds, códigos postales, ML webhook, ERP sync)
- **Then** every one of those tests passes unchanged, with no modification to
  their assertions or fixtures

### Scenario: Full backend suite stays green

- **Given** the dependency bump has been applied
- **When** `cd backend && pytest tests/ -v --tb=short` is run
- **Then** the full existing suite passes with no new failures attributable
  to the bump

## Requirement 2 — OpenAPI Exposure Gated by Environment

> Amended 2026-07-02 (review): CI runs ENVIRONMENT=testing — the gate is
> membership in `DEV_LIKE_ENVIRONMENTS = ("development", "testing")`, not a
> strict `== "development"` check.

The API contract endpoints (`/api/docs`, `/api/redoc`, `/api/openapi.json`)
MUST be reachable only when `ENVIRONMENT` is a member of
`DEV_LIKE_ENVIRONMENTS`, driven by a single gate.

### Scenario: Docs disabled outside dev-like environments

- **Given** `settings.ENVIRONMENT` is any value not in `DEV_LIKE_ENVIRONMENTS`
  (including unset/default)
- **When** a client requests `GET /api/docs`, `GET /api/redoc`, or
  `GET /api/openapi.json`
- **Then** each of the three requests returns `404 Not Found`

### Scenario: Docs enabled in development or testing

- **Given** `settings.ENVIRONMENT` is `"development"` or `"testing"`
- **When** a client requests `GET /api/docs`, `GET /api/redoc`, or
  `GET /api/openapi.json`
- **Then** each of the three requests returns `200 OK` with the expected
  content type (HTML for docs/redoc, JSON schema for openapi.json)

### Scenario: Single gate controls all three routes

- **Given** the app is configured with one environment-derived flag
- **When** that flag evaluates to "disabled"
- **Then** all three routes (`docs_url`, `redoc_url`, `openapi_url`) are
  disabled together — there is no code path where one is reachable while
  another is not, for the same `ENVIRONMENT` value

### Scenario: Fail-closed default

- **Given** `ENVIRONMENT` is not explicitly set in the runtime environment
- **When** the app starts and settings are loaded
- **Then** the effective value used for the gate is not a member of
  `DEV_LIKE_ENVIRONMENTS`, and the three routes are disabled (fail-closed
  default)

## Requirement 3 — `wipe-compras` Access Control

> **REVERSED 2026-07-16.** This requirement originally mandated an environment
> gate returning `404` outside `DEV_LIKE_ENVIRONMENTS` (shipped in PR #839,
> 2026-07-03). That contradicted an earlier recorded decision (2026-06-10) which
> had already accepted audit finding A-5 as a conscious risk and explicitly ruled
> out blocking this endpoint in security remediations. The gate made the endpoint
> unusable in production — the only environment where the compras module can
> currently be tested — so it was removed. The text below states the behavior
> that now holds; the superseded 404 requirement is preserved in
> `openspec/changes/archive/2026-07-03-security-quick-wins/`.

`POST /api/administracion/compras/testing/wipe-compras` MUST remain reachable in
every environment, production included, while the compras module is under
development. Access MUST be governed solely by the dedicated
`administracion.wipe_compras_testing` permission and the textual confirmation —
never by `settings.ENVIRONMENT`.

The endpoint MUST be removed outright when the compras module is complete. Until
then, finding A-5 stands as an accepted risk and MUST NOT be re-remediated by
gating or removing the route.

### Scenario: Endpoint reachable in production with the permission

- **Given** `settings.ENVIRONMENT` is `"production"`
- **And** the caller holds `administracion.wipe_compras_testing`
- **When** `POST .../testing/wipe-compras` is called with `confirmacion: "WIPE"`
- **Then** the wipe executes and the response is `200` — the environment does
  not affect reachability

### Scenario: Permission is the guard, in every environment

- **Given** any value of `settings.ENVIRONMENT`, production included
- **When** `POST .../testing/wipe-compras` is called
- **Then** access is governed exactly by:
  - anonymous/no token → `401`
  - authenticated but missing `administracion.wipe_compras_testing` → `403`
  - authenticated with the permission and valid input → `200`
  - authenticated with the permission and invalid input → `422`
- **And** a `404` MUST NOT be returned in any of these cases — a `404` would mean
  an environment gate has crept back in and silently displaced the permission
  check

### Scenario: Permission remains critical and narrowly granted

- **Given** the `permisos` table seeded by `compras_034_wipe_compras_permiso`
- **When** `administracion.wipe_compras_testing` is inspected
- **Then** it is flagged `es_critico = true` and granted only to the `SUPERADMIN`
  and `ADMIN` base roles

### Scenario: Every wipe is attributable

- **Given** a caller holding the permission triggers a wipe in any environment
- **When** the request is handled
- **Then** an audit line naming the actor (`usuario_id` and `username`) is logged
  BEFORE the deletion runs, so an attempt that dies half-way is still attributed
- **And** a second line records completion with the rows and tables affected, or
  the failure with the same actor
- **And** the lines carry no email or other PII — id and username are sufficient
  for attribution

> This audit trail is the second half of the mitigation the 2026-06-10 decision
> named alongside the dedicated permission. It is the only record of who
> triggered an irreversible wipe in production; it MUST NOT be dropped while the
> endpoint remains reachable.

### Scenario: Existing development-path tests keep passing

- **Given** the env-gate has been added
- **When** the existing test suite for `wipe-compras` is run with
  `ENVIRONMENT` set to `"development"` or `"testing"`
- **Then** all previously passing 401/403/422/200 assertions continue to pass
  unchanged

## Requirement 4 — Login Rate Limiting

`POST /api/auth/login` MUST be rate-limited per client IP, globally across all
backend worker processes, with a fail-open policy if the shared limiter
storage is unavailable.

### Scenario: Requests under the limit succeed normally

- **Given** a client has made fewer than the configured limit (default
  `10/minute`) of requests to `/api/auth/login` within the current window
- **When** the client sends another login request
- **Then** the request is processed normally (its outcome — `200` for valid
  credentials, `401` for invalid — is unaffected by the rate limiter)

### Scenario: Requests over the limit are throttled

- **Given** a client has reached the configured limit of requests to
  `/api/auth/login` within the current window (from the same key)
- **When** the client sends one more login request within that same window
- **Then** the response is `429 Too Many Requests` and includes a
  `Retry-After` header indicating when the client may retry

### Scenario: Limit is keyed by client IP, preferring Cloudflare header

- **Given** a request arrives with a `CF-Connecting-IP` header
- **When** the rate limiter computes the key for that request
- **Then** the key is the value of `CF-Connecting-IP`, not
  `X-Forwarded-For` and not the raw TCP peer address

### Scenario: Fallback key when Cloudflare header is absent

- **Given** a request arrives without a `CF-Connecting-IP` header (e.g. local
  development or a direct hit bypassing the tunnel)
- **When** the rate limiter computes the key for that request
- **Then** the key falls back to the direct client IP (`request.client.host`)

### Scenario: Limit is global across worker processes

- **Given** the backend runs as multiple worker processes (e.g. 4 uvicorn
  workers) behind the same load balancer
- **When** requests from the same client key are distributed across
  different workers
- **Then** the rate limit counter is shared (Redis-backed), so the total
  allowed requests across all workers combined equals the configured limit —
  not the limit multiplied by the worker count

### Scenario: Limit is configurable

- **Given** the rate limit is exposed as an application setting
- **When** no override is provided
- **Then** the effective default is `10/minute`
- **And** an operator can change the effective limit via configuration
  without a code change

### Scenario: Fail-open on limiter storage failure

- **Given** the Redis-backed limiter storage is unreachable (connection
  error, timeout, or any storage-layer exception)
- **When** a client sends a request to `/api/auth/login`
- **Then** the request proceeds to normal login processing as if no rate
  limit were configured (the request is NOT blocked, and no 429 or 5xx is
  returned due to the storage failure)
- **And** a warning is logged noting the limiter storage failure

### Scenario: Successful and failed login attempts both count

- **Given** a client is within the rate-limited window
- **When** the client makes a login request, regardless of whether the
  credentials are valid (`200`) or invalid (`401`)
- **Then** that request counts toward the client's rate limit window
  (the counter increments on every request reaching the endpoint, not only
  on failures)

### Scenario: Limiter state is resettable between tests

- **Given** the test suite exercises the rate-limited login endpoint across
  multiple test cases
- **When** each test starts
- **Then** the limiter's counter state for the test's key is isolated/reset
  so that one test's requests do not count toward another test's limit
  (no cross-test leakage causing flaky 429s)

## Requirement 5 — Non-Goals Guard

This change MUST NOT introduce rate limiting or exposure changes beyond the
four items above.

### Scenario: `/refresh` remains unthrottled

- **Given** the rate limiter is registered on the application
- **When** a client sends repeated requests to `/api/auth/refresh` beyond the
  login limit's threshold
- **Then** no rate limit is applied to `/refresh`, and the frontend's silent
  auto-refresh flow is unaffected

### Scenario: `/register` remains unthrottled by this change

- **Given** the rate limiter is registered on the application
- **When** a client sends repeated requests to `/api/auth/register`
- **Then** no new rate limit from this change applies to `/register`; its
  existing env-gate-403 behavior (from `auth.py:99-103`) is unchanged

### Scenario: No other audit findings are remediated by this change

- **Given** the security audit (`docs/auditoria-seguridad-stack-2026-06-10.md`)
  lists items beyond these four (JWT-in-localStorage, CSP headers, refresh
  token rotation, SQL-injection second-order fixes, localhost auth bypass,
  frontend sanitization)
- **When** this change is applied
- **Then** none of those other items are touched, modified, or partially
  addressed as a side effect
