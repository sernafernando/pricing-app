# Apply Progress — security-quick-wins

## Review amendments (2026-07-02)

Follow-up fixes applied on `fix/security-quick-wins-1` after code review of PR1:

1. **CI-breaking env gates**: CI runs `ENVIRONMENT=testing`
   (`.github/workflows/ci.yml:59`), but the docs gate and wipe-compras gate
   were keyed strictly to `"development"`, breaking CI. Introduced
   `DEV_LIKE_ENVIRONMENTS = ("development", "testing")` and
   `Settings.is_dev_or_test` in `backend/app/core/config.py`; `_docs_urls` in
   `backend/app/main.py` now checks membership instead of strict equality.
   Added `test_docs_enabled_in_testing` (RED before the fix, GREEN after).
2. **Shared env-gate dependency**: moved the wipe-compras env gate out of
   `administracion_compras.py` into a reusable `require_dev_or_test()`
   dependency in `backend/app/api/deps.py`. Added a `ponytail:` tech-debt
   marker above the route decorator (method-probe via `GET` still returns 405
   outside dev, revealing route existence) and a corresponding row in
   `docs/tech-debt-ledger.md`.
3. **Exception header forwarding**: `http_exception_handler` in
   `backend/app/core/exceptions.py` now forwards `exc.headers` (e.g. `Allow`
   on 405, `WWW-Authenticate` on 401) onto the JSONResponse. Added a
   `METHOD_NOT_ALLOWED` error code and 405→code mapping. Handler signature
   updated to `starlette.exceptions.HTTPException` (the class it's actually
   registered against). New tests in
   `backend/tests/unit/test_exception_handler_headers.py`.
4. **Dependency hygiene**: pinned `python-multipart==0.0.32` (exact, matching
   the version installed/tested in the venv) instead of the range pin.
   Line-ending note: `backend/requirements.txt` has pre-existing mixed
   CRLF/LF endings inherited from `origin/main` unrelated to this change; only
   the `python-multipart` line's value was modified, its line ending left
   untouched to avoid unrelated diff noise.
5. **Spec amendment**: `specs/security-quick-wins.md` Requirements 2 and 3
   updated from `ENVIRONMENT == "development"` to membership in
   `DEV_LIKE_ENVIRONMENTS`.

All originally-committed PR1 work (work units 1.x — python-multipart CVE
bump, env-gated OpenAPI docs, wipe-compras 404 hardening) still applies as
recorded in Engram (`sdd/security-quick-wins/apply-progress`, obs #730).

## PR2 — Login Rate Limiting (2026-07-03, branch `feat/login-rate-limit`)

All work units 2.1–2.9.1 complete (2.9.2 — opening the PR — intentionally
out of scope for this apply run). Commits:
`62018c48` refactor(auth): rename login body param to credentials,
`04013460` feat(auth): rate-limit login endpoint (10/minute per IP, fail-open).

### Deviations from design.md (documented in tasks.md 2.7.2)

1. **`headers_enabled=False` with manual `Retry-After` header construction** (shipped
   implementation differs from design.md §5). Design §5 described using slowapi's
   `_inject_headers()` call in the custom 429 handler to write rate-limit headers.
   The final implementation instead sets `headers_enabled=False` on the
   `Limiter` and manually constructs the `Retry-After` header in the 429 handler
   using the parsed rate-limit window (see `backend/app/core/rate_limit.py:78-102`).
   This avoids slowapi's success-path `get_window_stats()` call (a second Redis
   round-trip on every login attempt) while preserving the identical response
   contract: a `429` status with `Retry-After` header and the centralized error
   envelope. The `login()` endpoint has no `response: Response` parameter — the
   fix is purely in the limiter module, keeping the endpoint signature clean.

2. **Fail-open test targets `Limiter._limiter.storage`, not
   `app.state.limiter`.** The `@limiter.limit(...)` decorator closes over the
   route's own `Limiter` instance directly (`self.limiter`, a `limits`
   strategy object bound to a storage instance at `__init__` time) — it never
   reads `request.app.state.limiter` (that attribute is only consulted by the
   custom 429 exception handler, for header injection on the 429 response
   itself). The first draft of the fail-open test swapped
   `app.state.limiter` for a broken instance and passed even with
   `swallow_errors=False` — a false green. Per task 2.7.2's built-in
   suspicion clause, the test was fixed to monkeypatch
   `route_limiter._limiter.storage` directly; re-running with
   `swallow_errors=False` then produced a genuine `500`, proving the test
   exercises the real failure path before restoring `swallow_errors=True`.

### Verification

- `backend/tests/unit/test_login_rate_limit.py` (new, 8 tests): 3 unit tests
  for `client_ip_key`, 429 + Retry-After, cross-test isolation, fail-open
  (with the temporary-break proof documented above), 2 non-goals-guard tests
  for `/refresh` and `/register`.
- CI simulation: `ENVIRONMENT=testing pytest tests/unit/test_login_rate_limit.py
  tests/integration/test_auth_flows.py` → 21 passed.
- Full suite: `pytest tests/ -q --ignore=tests/test_turbo_simple.py` → **1771
  passed, 15 skipped** (baseline before this PR: 1763 passed, 15 skipped — the
  +8 delta is exactly the new rate-limit test file; zero regressions).
- Lint: `ruff check` + `ruff format` clean on all changed files (format was
  auto-applied to `rate_limit.py` and `test_login_rate_limit.py` before the
  final commit, per the repo's format-check pre-commit hook).
- No Redis in CI (`.github/workflows/ci.yml` has no `services:` block) — all
  tests run against `memory://` storage, set via
  `RATE_LIMIT_STORAGE_URI=memory://` in `conftest.py` before `from app.main
  import app`.

### Not done in this apply run (explicitly out of scope)

- 2.9.2 — opening PR2 against `main`. No push, no PR created, per explicit
  instruction.
