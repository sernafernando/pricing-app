# Archive Report — security-quick-wins

**Date**: 2026-07-03  
**Change**: `security-quick-wins`  
**Status**: Archived and closed  
**Verdict**: Verification PASS (no CRITICAL blockers)

---

## Executive Summary

Backend security hardening: June 2026 audit week-1 quick wins. Four low-risk, high-value fixes delivered as two independent PRs to `main` (PR #839, #840, both merged): python-multipart CVE-2024-24762 remediation, OpenAPI docs environment gating, wipe-compras endpoint 404 hardening, and login rate limiting (10/minute per Cloudflare IP, fail-open on Redis outage). Verification passed; canonical spec created and synced.

---

## What Shipped

### PR #839 — Mechanical Hardening (fix/security-quick-wins-1)

**Merged**: 2026-07-02  
**Requirements**: 1, 2, 3 (python-multipart CVE, docs env-gate, wipe-404)

- `backend/requirements.txt`: `python-multipart==0.0.32` (exact pin; CVE-2024-24762 remediated)
- `backend/app/main.py`: `_docs_urls()` pure helper + env-gate spread; single flag controls all three routes (`docs_url`, `redoc_url`, `openapi_url`)
- `backend/app/api/deps.py`: `require_dev_or_test()` reusable dependency
- `backend/app/routers/administracion_compras.py`: wipe-compras 404 hardening (route-level dependency before permission guard)
- `backend/app/core/config.py`: `DEV_LIKE_ENVIRONMENTS = ("development", "testing")` tuple
- `backend/app/core/exceptions.py`: header forwarding for `Allow`, `WWW-Authenticate` on 405/401
- Tests: `test_docs_gate.py`, `test_wipe_compras.py` (404 indistinguishability), `test_exception_handler_headers.py`

### PR #840 — Login Rate Limiting (feat/login-rate-limit)

**Merged**: 2026-07-03  
**Requirement**: 4 (login brute-force throttling)

- `backend/app/core/rate_limit.py`: `Limiter`, `client_ip_key()`, 429 handler (new module; `headers_enabled=False` + manual Retry-After construction)
- `backend/app/main.py`: limiter wiring (3 lines: `app.state.limiter`, exception handler, middleware)
- `backend/app/core/config.py`: `LOGIN_RATE_LIMIT: str = "10/minute"`, `RATE_LIMIT_STORAGE_URI: Optional[str]` settings
- `backend/app/core/exceptions.py`: `ErrorCode.RATE_LIMITED`, `429: ErrorCode.RATE_LIMITED` in `_status_to_code`
- `backend/app/api/endpoints/auth.py`: `request: Request` param injection, `@limiter.limit(settings.LOGIN_RATE_LIMIT)` decorator, body param rename to `credentials`
- `backend/tests/conftest.py`: `RATE_LIMIT_STORAGE_URI=memory://` before app import
- Tests: `test_login_rate_limit.py` (429, fail-open, isolation, key function, non-goals guard; 8 tests)
- `backend/requirements.txt`: `slowapi==0.1.10` added
- Aggregate test result: **1771 passed, 15 skipped** (zero regressions vs. baseline)

---

## Verification Verdict

**Status**: PASS  
**Test Coverage**: 21 dedicated tests + full suite (1771 tests)

Per-requirement results:
1. **python-multipart CVE remediation**: PASS (0.0.32 > 0.0.20, CVE-2024-24762 fixed; all upload tests green)
2. **OpenAPI docs env-gate**: PASS (membership in `DEV_LIKE_ENVIRONMENTS` controls all three routes; fail-closed default)
3. **wipe-compras 404 hardening**: PASS (404 indistinguishable from unknown route; permission guard retained; existing tests pass)
4. **Login rate limiting**: PASS (10/minute global limit, CF-Connecting-IP keyed, fail-open on Redis outage, test isolation via `Limiter.reset()`)
5. **Non-goals guard**: PASS (`/refresh` unthrottled, `/register` unmodified)

**Findings**:
- **CRITICAL**: None
- **WARNING**: 1 — wipe-compras GET method-probe still returns 405 (reveals route existence via HTTP method); tracked in `docs/tech-debt-ledger.md`, acceptable residual risk
- **SUGGESTION (resolved)**: apply-progress.md "Deviations" section corrected to match final shipped implementation (`headers_enabled=False` + manual Retry-After, no `response: Response` param in `login()`)

---

## Canonical Spec

**Location**: `openspec/specs/backend/security-hardening/spec.md` (NEW)

Canonical spec created and synced from change artifacts:
- 5 Requirements (python-multipart CVE, docs env-gate, wipe-404, login rate limiting, non-goals guard)
- 37 scenarios with Given-When-Then acceptance criteria
- Includes 2026-07-02 amendment: `DEV_LIKE_ENVIRONMENTS = ("development", "testing")`

Full content merged from spec delta. Marked "Active (canonical source of truth)" with origin and last-updated date (2026-07-03).

---

## Residual Tech Debt

### Known Open: wipe-compras GET method-probe (Accept: 405)

- **Location**: `POST /api/testing/wipe-compras` (administracion_compras.py:4732)
- **Issue**: A `GET` request to the route returns `405 Method Not Allowed` outside dev/test environments, which reveals the route exists (distinguishable from a genuinely unknown route via HTTP method, though not via POST)
- **Tracking**: `docs/tech-debt-ledger.md` (ponytail marker in code)
- **Risk**: Low — POST scenario (audit requirement) is fully covered (404 indistinguishable from unknown); GET method-probe is an advanced vector
- **Action**: Deferred — would require additional env-gate at method level or route registration rewrite; out of scope for this change

---

## Archive Layout

```
openspec/changes/archive/2026-07-03-security-quick-wins/
├── proposal.md                           (rationale, scope, risks)
├── design.md                             (technical shape, ADRs, placement decisions)
├── tasks.md                              (work units, checklists, forecasts)
├── apply-progress.md                     (amendments, deviations, verification)
├── verify-report.md                      (per-requirement results, alignment)
├── archive-report.md                     (this file)
└── specs/backend/security-hardening/
    └── spec.md                           (delta: 5 requirements, 37 scenarios)
```

---

## Artifact State

- **Change folder**: `openspec/changes/security-quick-wins/` (original, now out of use)
- **Archive folder**: `openspec/changes/archive/2026-07-03-security-quick-wins/` (all artifacts preserved, structure conformed)
- **Canonical spec**: `openspec/specs/backend/security-hardening/spec.md` (synchronized, authoritative)

**Note**: Flat spec file `openspec/changes/security-quick-wins/specs/security-quick-wins.md` has been reshaped to nested structure `specs/backend/security-hardening/spec.md` per repository convention. Original flat file location superseded by archive layout.

---

## Related Issues / Cross-References

- Security audit: `docs/auditoria-seguridad-stack-2026-06-10.md` (June 10, 2026)
- PRs: #839 (mechanical), #840 (rate limiting)
- Test suites:
  - `backend/tests/unit/test_docs_gate.py`
  - `backend/tests/compras/test_wipe_compras.py`
  - `backend/tests/unit/test_login_rate_limit.py`
  - `backend/tests/unit/test_exception_handler_headers.py`
- Tech debt ledger: `docs/tech-debt-ledger.md`

---

## Next Steps

**None** — change is complete and closed. All four requirements are shipped and verified. Canonical spec is synchronized. Residual tech debt (wipe-compras GET 405) is tracked and accepted as low-risk.

If follow-up is needed:
- Wipe-compras GET method-probe fix: would require separate SDD change (`sdd-new` for HTTP method hardening)
- JWT httpOnly migration: separate audit item, out of scope (listed in non-goals)
- CSP headers / refresh-token rotation: separate audit items, deferred

---

**Archived by**: sdd-archive phase  
**Archive timestamp**: 2026-07-03  
**Project**: pricing-app  
**Status**: CLOSED
