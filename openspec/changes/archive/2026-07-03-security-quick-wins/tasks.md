# Tasks: Security Quick Wins

> Delivery: 2 independent PRs to `main` (stacked, both independently mergeable).
> Strict TDD: each behavior-changing task has its failing test written and
> confirmed red BEFORE the implementation task.

---

## PR1 — Mechanical Hardening (multipart bump + docs env-gate + wipe 404)

Branch: `fix/security-quick-wins-1`

Covers spec Requirements 1, 2, 3.

### Work Unit 1.1 — Resolve wipe-test env regression risk (design §10.2)

- [x] 1.1.1 Inspect current test process default `ENVIRONMENT` for
      `backend/tests/compras/test_wipe_compras.py` (check for a test `.env` /
      `conftest.py` override). Confirm whether default is `development` or
      `production`.
- [x] 1.1.2 Decide and pin the approach per design §10.2:
  - **Option (a)**: add an autouse fixture in `test_wipe_compras.py` that sets
    `ENVIRONMENT="development"` for all existing tests, with only the new 404
    test overriding to `"production"`.
  - **Option (b)**: if test env already defaults to `development`, leave
    existing tests untouched; only the new test overrides to `"production"`.
- [x] 1.1.3 Document the chosen option inline as a comment in the test file.

(This is a decision/setup task, not itself a behavior change — no red/green
cycle required, but it gates 1.4 below.)

### Work Unit 1.2 — `python-multipart` CVE bump (Requirement 1)

- [x] 1.2.1 No new test required (per design — covered by existing upload
      suite staying green). Confirm current pin at
      `backend/requirements.txt:40` (`python-multipart==0.0.6`).
- [x] 1.2.2 Bump `backend/requirements.txt` to
      `python-multipart>=0.0.20,<0.1`. `pip install -r requirements.txt`.
- [x] 1.2.3 Verification gate: re-run the existing upload/attachment test
      suites unchanged — `test_compras_adjuntos_endpoints.py` and all other
      suites touching upload endpoints (etiquetas ZPL/upload/colecta, caja,
      RRHH, tickets, sounds, códigos postales, ML webhook, ERP sync). All
      must pass with zero assertion/fixture changes.

### Work Unit 1.3 — Env-gate OpenAPI docs (Requirement 2)

- [x] 1.3.1 **RED**: write `backend/tests/.../test_docs_gate.py` (new file)
      with `test_docs_disabled_outside_development` and
      `test_docs_enabled_in_development`, asserting the shape of a not-yet-
      existing `_docs_urls(environment: str)` helper (import will fail /
      function will not exist → red). See design §10.1 for exact assertions.
- [x] 1.3.2 Confirm red: `pytest backend/tests/.../test_docs_gate.py -v`
      fails (ImportError / AttributeError).
- [x] 1.3.3 **GREEN**: implement `_docs_urls(environment: str) -> dict` in
      `backend/app/main.py` (pure function, per design §2) and spread its
      result into the `FastAPI(...)` constructor, replacing the hardcoded
      `docs_url`/`redoc_url`/`openapi_url` kwargs.
- [x] 1.3.4 Confirm green: `pytest backend/tests/.../test_docs_gate.py -v`
      passes.
- [x] 1.3.5 Verification gate: confirm no other docs-URL references exist in
      `main.py` (no custom docs routes, no `get_openapi()` override) — already
      audited in design, re-confirm with a grep before merging.

### Work Unit 1.4 — `wipe-compras` 404 hardening (Requirement 3)

Depends on 1.1 (env decision must be pinned first).

- [x] 1.4.1 **RED**: add `test_wipe_returns_404_outside_development` to
      `backend/tests/compras/test_wipe_compras.py` per design §10.2 — sets
      `ENVIRONMENT="production"` via monkeypatch, POSTs to the route, and
      asserts the response is **byte-equal** (status, JSON body, content-type)
      to a control POST against a genuinely unknown route
      (`/api/this-route-does-not-exist-xyz`).
- [x] 1.4.2 Confirm red: run the new test — must fail (route currently
      reachable in all environments given valid auth/permission).
- [x] 1.4.3 **GREEN**: implement `_require_development_env()` dependency in
      `backend/app/routers/administracion_compras.py` (bare
      `HTTPException(status_code=404)`, no custom detail — see design §3.2)
      and attach it via `dependencies=[Depends(_require_development_env)]` on
      the `@router.post("/testing/wipe-compras", ...)` decorator (route-level,
      not parameter-level, per design §3.1 placement decision).
- [x] 1.4.4 Confirm green: new test passes.
- [x] 1.4.5 Apply the env-decision from 1.1 to the existing wipe tests
      (`test_wipe_requires_auth`, `_requires_permiso`,
      `_requires_confirmation_string`, `_clears_all_tables`, `_fk_regression`)
      so they keep exercising the 401/403/422/200 paths unchanged.
- [x] 1.4.6 Verification gate: run the full `test_wipe_compras.py` file — all
      previously-passing assertions (401/403/422/200) still pass, plus the new
      404 test.

### Work Unit 1.5 — PR1 full regression gate

- [x] 1.5.1 Run `cd backend && source venv/bin/activate && pytest tests/ -v --tb=short`
      (full suite) — no new failures attributable to the bump, the docs gate,
      or the wipe 404.
- [ ] 1.5.2 Open PR1 against `main` from `fix/security-quick-wins-1`.

**PR1 Review Workload Forecast**
- Estimated changed lines: ~40–60 (1-line requirements.txt bump, ~15-line
  `_docs_urls` helper + wiring, ~10-line env-gate dependency + decorator
  change, ~30–50 lines of new/adjusted tests).
- Chained PRs recommended: No (self-contained, independently mergeable).
- 400-line budget risk: Low.
- Decision needed before apply: No.

---

## PR2 — Login Rate Limiting (item 4)

Branch: `feat/login-rate-limit`

Covers spec Requirement 4 (and guards Requirement 5 non-goals — no new tests
needed for §5, verified by absence of changes to `/refresh` and `/register`).

Depends on PR1 only for the shared `main.py` diff base if PR1 has already
merged; otherwise both branches fork from the same commit and PR2 can be
opened independently (stacked-to-main: rebase onto `main` after PR1 merges,
or resolve the two-line `main.py` conflict at merge time).

### Work Unit 2.1 — Rename login body param BEFORE the limiter decorator

- [x] 2.1.1 **RED**: no new test yet — this is a pure refactor with the
      existing login tests as the regression harness. Run the existing login
      test suite first to capture the green baseline.
- [x] 2.1.2 Confirm baseline green: `pytest backend/tests/.../test_auth*.py -v`
      (or wherever login tests live) passes before the rename.
- [x] 2.1.3 **Implement** the rename in `backend/app/api/endpoints/auth.py`:
      rename the login body parameter `request: LoginRequest` →
      `credentials: LoginRequest`, and update all 4 internal references
      (`request.username` ×2, `request.password` ×2 per design — verify exact
      count in source) to `credentials.username` / `credentials.password`.
      Do NOT add `request: Request` or the `@limiter.limit(...)` decorator in
      this task — rename only.
- [x] 2.1.4 Confirm still green: re-run the existing login test suite — must
      pass unchanged (pure rename, no behavior change).

### Work Unit 2.2 — Rate-limit config + error code plumbing

- [x] 2.2.1 Add `LOGIN_RATE_LIMIT: str = "10/minute"` and
      `RATE_LIMIT_STORAGE_URI: Optional[str] = None` to `Settings` in
      `backend/app/core/config.py` (design §8).
- [x] 2.2.2 Add `ErrorCode.RATE_LIMITED = "RATE_LIMITED"` in
      `backend/app/core/exceptions.py` and extend `_status_to_code` with
      `429: ErrorCode.RATE_LIMITED`.
- [x] 2.2.3 Add `slowapi==0.1.10` to `backend/requirements.txt`,
      `pip install -r requirements.txt`.

### Work Unit 2.3 — Test harness: `RATE_LIMIT_STORAGE_URI` before app import

- [x] 2.3.1 Edit `backend/tests/conftest.py`: add
      `os.environ.setdefault("RATE_LIMIT_STORAGE_URI", "memory://")` at the
      very top of the file, above `from app.main import app` and above any
      other import that transitively imports `app.core.config` (design §9,
      ordering-sensitive — this MUST land before the rate-limit module or app
      module exists, so it is a no-op today until 2.4 creates
      `app/core/rate_limit.py`, but must be in place before that module's
      first import in a test run).

### Work Unit 2.4 — `client_ip_key` (Requirement 4, IP-keying scenarios)

- [x] 2.4.1 **RED**: write `backend/tests/.../test_login_rate_limit.py` with
      unit tests for `client_ip_key` (no app/TestClient needed, per design
      §9.4): (a) `CF-Connecting-IP` header present → returned; (b) header
      absent, `request.client.host` set → fallback returned; (c)
      `X-Forwarded-For` present but `CF-Connecting-IP` absent → XFF is
      ignored, `client.host` is used (spoof-safety regression).
- [x] 2.4.2 Confirm red: fails on import (`app.core.rate_limit` does not
      exist yet).
- [x] 2.4.3 **GREEN**: create `backend/app/core/rate_limit.py` with
      `client_ip_key(request: Request) -> str` per design §6 (priority:
      `CF-Connecting-IP` → `request.client.host` → `"unknown"`, XFF never
      consulted).
- [x] 2.4.4 Confirm green: the 3 key-function unit tests pass.

### Work Unit 2.5 — Limiter + 429 handler + wiring

- [x] 2.5.1 **RED**: extend `test_login_rate_limit.py` with the 429 test
      (design §9.1): hit `POST /api/auth/login` 11 times from the same
      `TestClient` (no `CF-Connecting-IP` → single shared key); assert
      requests 1–10 process normally (200/401 per credentials) and request 11
      returns `429` with body
      `{"error": {"code": "RATE_LIMITED", "message": ...}}` and a
      `Retry-After` header present.
- [x] 2.5.2 Confirm red: fails (no rate limiting exists yet — all 11 requests
      succeed/fail normally, no 429).
- [x] 2.5.3 **GREEN**, in order:
  - Add `Limiter`, `limiter` instance, and `rate_limit_exceeded_handler` to
    `backend/app/core/rate_limit.py` (design §5: `swallow_errors=True`,
    `strategy="fixed-window"`, `default_limits=[]`,
    `storage_uri=settings.RATE_LIMIT_STORAGE_URI or settings.REDIS_URL`).
  - Wire into `backend/app/main.py`: `app.state.limiter = limiter`,
    `app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)`,
    `app.add_middleware(SlowAPIMiddleware)`, and set
    `logging.getLogger("slowapi").setLevel(logging.WARNING)`.
  - In `backend/app/api/endpoints/auth.py`: add `request: Request` parameter
    to `login(...)` (alongside the now-renamed `credentials: LoginRequest`
    from Work Unit 2.1) and decorate with
    `@limiter.limit(settings.LOGIN_RATE_LIMIT)`.
  - **Deviation from design (documented)**: also added `headers_enabled=True`
    to `Limiter(...)` and a `response: Response` parameter to `login(...)`.
    Without `headers_enabled=True`, slowapi's `_inject_headers` no-ops
    entirely (including inside our custom 429 handler), so `Retry-After`
    never appears. But `headers_enabled=True` alone makes the decorator's
    sync wrapper unconditionally call `_inject_headers(kwargs.get("response"), ...)`
    after every request, which raises if `response` isn't a `Response`
    instance — and `login` returns a `TokenResponse` Pydantic model (via
    `response_model`), not a raw `Response`, causing a 500 on every
    successful/failed login. Adding `response: Response` as an endpoint
    parameter (the standard slowapi/FastAPI idiom for this exact case) gives
    the decorator a real `Response` object to write headers into, which
    FastAPI merges into the final response. Verified via full regression
    (2.9) and the CI-simulation run.
- [x] 2.5.4 Confirm green: the 429 test passes; requests 1–10 still return
      their normal 200/401 outcomes.

### Work Unit 2.6 — Test isolation between test cases (design §9.2)

- [x] 2.6.1 **RED**: with the 429 test from 2.5 already in place, add a
      second, independent test in the same module asserting a client can make
      a fresh full quota of login attempts (proves no cross-test leakage).
      Run the full file — expect this second test to fail/be flaky due to
      counter leakage from 2.5's test (confirms the isolation gap is real).
- [x] 2.6.2 **GREEN**: add an autouse fixture (design §9.2) that resets
      `app.state.limiter`'s storage before and after each test (verify exact
      reset API against the installed slowapi/limits version —
      `Limiter.reset()` or `app.state.limiter._storage.reset()`/`.clear()`).
      Used `Limiter.reset()` — available and working in slowapi 0.1.10.
- [x] 2.6.3 Confirm green: both tests pass independently and when run
      together/repeated.

### Work Unit 2.7 — Fail-open on storage failure (design §9.3)

- [x] 2.7.1 **RED**: write the fail-open test — point the limiter at an
      unreachable storage (e.g. `storage_uri="redis://127.0.0.1:1/0"`,
      `swallow_errors=True`), then `POST /api/auth/login` with valid
      credentials and assert `200` (not blocked, not 500). Also assert a
      warning was logged via
      `caplog.set_level(logging.WARNING, logger="slowapi")`.
- [x] 2.7.2 Confirm red: **this came up green on the first write**, exactly
      the scenario the task anticipated — proof was required. Discovered that
      naively swapping `app.state.limiter` for a broken `Limiter` instance
      does nothing: the `@limiter.limit(...)` decorator closes over the
      **module-level `limiter` singleton directly** (`self.limiter` inside
      slowapi, read from the decorated-route's own `Limiter` instance — NOT
      `request.app.state.limiter`, which is consulted only by the custom 429
      handler for header injection). Further, `Limiter.limiter` is a
      `limits`-library strategy object (`self._limiter`) bound to a storage
      instance at `Limiter.__init__` time; reassigning `Limiter._storage`
      afterwards has no effect since the strategy already captured the
      original storage reference. Fixed the test to monkeypatch
      `route_limiter._limiter.storage` (the actually-consulted storage
      object) instead. With that fix AND `swallow_errors` temporarily flipped
      to `False` in `rate_limit.py`, the test failed with a real `500`,
      proving the test exercises the genuine failure path. See test
      docstring in `test_fail_open_when_storage_unreachable` for the full
      explanation — this is a load-bearing comment against a real footgun.
- [x] 2.7.3 Confirm final green with `swallow_errors=True` restored: login
      succeeds despite dead storage, warning logged.

### Work Unit 2.8 — Non-goals guard (Requirement 5)

- [x] 2.8.1 Add or confirm a lightweight test asserting `/api/auth/refresh`
      is NOT decorated with the limiter (e.g. repeated calls beyond
      `LOGIN_RATE_LIMIT` threshold never return 429) and `/api/auth/register`
      behavior is unchanged (still governed solely by its existing env-gate
      403, not by the new rate limiter).
- [x] 2.8.2 Confirm green.

### Work Unit 2.9 — PR2 full regression gate

- [x] 2.9.1 Run `cd backend && source venv/bin/activate && pytest tests/ -v --tb=short`
      (full suite) — no new failures, especially confirm the rest of the auth
      test suite still passes after the `credentials` rename. Result:
      **1771 passed, 15 skipped** (baseline 1763 passed / 15 skipped + 8 new
      tests in `test_login_rate_limit.py` = exact match, zero regressions).
      Also ran the CI-simulation gate
      (`ENVIRONMENT=testing pytest tests/unit/test_login_rate_limit.py
      tests/integration/test_auth_flows.py`) — 21 passed. This run is what
      surfaced the `headers_enabled`/`response: Response` deviation above
      (only failed under `ENVIRONMENT=testing`... actually reproduced under
      default env too once isolated — see commit history for the fix).
- [ ] 2.9.2 Open PR2 against `main` (or stacked on PR1's branch per chosen
      chain strategy) from `feat/login-rate-limit`. **Not done — explicitly
      out of scope for this apply run** (orchestrator instructed: do not
      push, do not open a PR).

**PR2 Review Workload Forecast**
- Estimated changed lines: ~120–160 (new `rate_limit.py` ~50 lines, config +
  exceptions ~10 lines, `main.py` wiring ~6 lines, `auth.py` rename + decorator
  ~10 lines, `conftest.py` ~2 lines, new test file ~80–100 lines).
- Chained PRs recommended: No (self-contained; independently mergeable even
  though it stacks conceptually on PR1's `main.py` state).
- 400-line budget risk: Low.
- Decision needed before apply: No.

---

## Cross-cutting notes

- Both PRs touch `backend/app/main.py`; if PR1 has not yet merged when PR2
  starts, expect a small rebase/merge step on `main.py` (docs-gate spread +
  limiter wiring are additive, non-overlapping lines).
- No Alembic migration in either PR (per design §11).
- `slowapi==0.1.10` is the only new runtime dependency, added in PR2 only.
