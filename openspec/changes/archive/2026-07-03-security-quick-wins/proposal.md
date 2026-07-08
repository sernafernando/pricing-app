# Proposal: Security Quick Wins — June Audit Week-1 Hardening

> Change: `security-quick-wins`
> Four low-risk, high-value security fixes from the 2026-06-10 stack security
> audit (`docs/auditoria-seguridad-stack-2026-06-10.md`). All four were
> re-verified as **still open on `main` at 2026-07-02**. No user-facing behavior
> change: this is pure attack-surface reduction and brute-force friction.
> Delivered as **two independent PRs to `main`** (PR1 mechanical, PR2 rate limiting).

## Why

The security audit landed on **2026-06-10**. Three weeks later, on **2026-07-02**,
**zero** of its week-1 quick wins had been remediated — every item below is still
live on `main`. These are not deep refactors; they are the cheapest, safest wins
in the audit ("top 5 acciones inmediatas" and the ALTO backend findings), and the
longer they stay open the longer the app runs with a known-CVE dependency, a fully
public API contract, a destructive test endpoint reachable in production, and a
login with no brute-force friction.

The four items, mapped to the audit:

1. **`python-multipart==0.0.6` → CVE-2024-24762 (DoS).** Audit "acción inmediata
   #2": a one-line dependency bump. `requirements.txt:40`. FastAPI 0.104.1 declares
   `python-multipart>=0.0.5` as an optional extra with no pinned upper bound, so
   bumping to `>=0.0.20,<0.1` is compatible. The app only touches multipart via
   FastAPI `UploadFile`/`File(...)` (20 files), never multipart internals directly.

2. **OpenAPI docs public in production.** Audit finding **A-2**: `/api/docs`,
   `/api/redoc`, and `/api/openapi.json` are served unauthenticated in production
   (`main.py:207-215`), exposing the full API contract — including the wipe
   endpoint — to anyone. No internal consumer of `/api/openapi.json` exists (no
   frontend codegen, no monitoring reference), so it is safe to disable outside
   `development`.

3. **`wipe-compras` reachable in production.** Audit finding **A-5**: the
   destructive `/api/testing/wipe-compras` endpoint
   (`administracion_compras.py:4726-4736`) is guarded **only** by a permission
   check (`administracion.wipe_compras_testing`). Its own permission name says
   "testing" — no legitimate production/staging workflow depends on it. It should
   not even *exist* to production clients.

4. **No rate limiting on login.** Audit finding **A-4**: `/api/auth/login`
   (`auth.py:48`) has no per-IP or per-user throttling — credential brute-force
   runs with zero friction. Audit recommends `slowapi` with a limit like
   `10/minute`.

Success =

1. The known multipart CVE is closed and every upload path still works.
2. The API contract (`/api/docs`, `/api/redoc`, `/api/openapi.json`) is **not
   reachable** outside `development`.
3. `/api/testing/wipe-compras` returns **404** outside `development` — it does not
   confirm its own existence to production clients.
4. `/api/auth/login` returns **429** after a per-client threshold, throttling
   brute-force globally across all 4 uvicorn workers.
5. Each fix is **locked by a test**, and the **entire existing backend suite stays
   green** (`cd backend && source venv/bin/activate && pytest`).

## What Changes

Four independent hardening changes. None alters a successful request's response
shape or any legitimate user workflow. Fixed infrastructure constraints (from the
user-decisions round, **do NOT re-litigate**) are encoded inline below.

### Item 1 — Bump `python-multipart` (mechanical)

- `requirements.txt`: `python-multipart==0.0.6` → `python-multipart>=0.0.20,<0.1`.
- No app-code change: the codebase never calls multipart internals (only FastAPI
  `UploadFile`/`File(...)`). The `0.0.6→0.0.7` removal of the deprecated
  `parse_options_header` does not affect app code.
- Regression is covered by **re-running the existing upload tests** after the bump
  (20 upload sites: etiquetas ZPL/upload/colecta, compras adjuntos, caja, RRHH,
  tickets, sounds, códigos postales, ML webhook, ERP sync). No new upload logic.

### Item 2 — Env-gate the OpenAPI docs (single flag)

- In `main.py`, compute one flag `_docs_enabled = settings.ENVIRONMENT == "development"`
  and pass `docs_url=... if _docs_enabled else None`, `redoc_url=... else None`,
  `openapi_url=... else None`.
- **One flag suffices for all three**: Swagger UI (`/api/docs`) and ReDoc
  (`/api/redoc`) both fetch the OpenAPI schema, so disabling `openapi_url` also
  disables them — but we set all three to `None` explicitly for clarity.
- `settings.ENVIRONMENT` already defaults to `"production"` (`config.py:26`), so
  this is **fail-closed by default** (missing/unset env → docs disabled).

### Item 3 — `wipe-compras` returns 404 outside development (new env-gate-404 pattern)

- At the top of the `wipe_compras_endpoint` function, **before** the existing
  permission guard, add:
  `if settings.ENVIRONMENT != "development": raise HTTPException(status_code=404)`.
- **404, not 403** (audit intent): a 403 confirms the endpoint exists; a 404 makes
  it indistinguishable from a nonexistent route to production clients.
- The **permission guard stays** (`administracion.wipe_compras_testing`) — the
  env-gate is defense-in-depth layered *on top of*, not *instead of*, authz.
- This establishes a reusable **env-gate-404** pattern (distinct from the existing
  env-gate-403 precedent at `auth.py:99-103` for `/register`, which intentionally
  reveals a 403 for a known-public route).

### Item 4 — Rate-limit `/api/auth/login` with slowapi + Redis

Fixed constraints from the decisions round (encode, do NOT reopen):

- **Topology:** Cloudflare Tunnel → nginx → uvicorn (4 workers). The real client
  IP arrives in the **`CF-Connecting-IP`** header (trustworthy: the origin is only
  reachable through the tunnel). `X-Forwarded-For` may contain Cloudflare IPs and
  must NOT be used as the key.
- **Storage:** `slowapi` + **Redis** storage (`REDIS_URL` already in `config.py:68`
  for SSE pub/sub). A shared Redis store makes the limit **global across the 4
  workers**, not per-worker. Compat verified via `pip install --dry-run`:
  slowapi 0.1.10 + limits 5.8.0 + Deprecated + wrapt — does **not** touch pinned
  `fastapi==0.104.1` / `starlette==0.27.0`.
- **Scope:** `/api/auth/login` **ONLY** (per audit; `/register` is already
  env-gated, `/refresh` is deliberately excluded to avoid throttling the frontend
  auto-refresh loop).
- **Key function:** `CF-Connecting-IP` header, with fallback to the direct client
  IP (`request.client.host`) when the header is absent (e.g. local development or
  a direct hit). This keeps local dev usable and never keys on a Cloudflare edge IP.
- **Limit:** `10/minute` per client IP (see rationale below).
- Add `slowapi` to `requirements.txt`; register the `Limiter` on the app and the
  `RateLimitExceeded` → 429 handler; decorate only the login route.

**Why 10/minute?** It sits well above any human login cadence (a real user retries
2–4 times, not 10) yet caps an attacker at 600 attempts/hour per IP instead of
thousands. It matches the audit's own suggested figure (`A-4: "10/minute"`), so it
needs no separate justification round. The exact number is trivially tunable later
via a single config value; design/spec can expose it as a setting if desired, but
`10/minute` is the shipping default.

## Scope / Non-Goals

### In Scope

**PR1 — Mechanical hardening (items 1–3):** low-risk, no new dependency, small diff.
- `python-multipart` version bump + existing upload tests re-run.
- Single-flag env-gate for `/api/docs`, `/api/redoc`, `/api/openapi.json`.
- Env-gate-404 guard on `wipe-compras` (permission guard retained).
- New tests: docs disabled in prod-env, wipe returns 404 in prod-env.

**PR2 — Login rate limiting (item 4):** new dependency + infra-coupled, more
careful review.
- `slowapi` added, Redis-backed limiter, `CF-Connecting-IP`-keyed, `10/minute` on
  `/api/auth/login` only.
- New test: login returns 429 after N attempts.

### Out of Scope (explicitly deferred)

These audit items are **not** part of this change and must not be pulled in:

- **JWT-in-`localStorage` → httpOnly cookie migration** (audit "acción #3"): large
  frontend + backend auth refactor, separate change.
- **Content-Security-Policy headers.**
- **Refresh-token revocation / rotation.**
- **Rate limiting on `/register` or `/refresh`** — login only, per the decision.
  `/register` is already env-gated; `/refresh` throttling would break the
  frontend's silent auto-refresh.
- **SQL-injection second-order fixes** (audit C-1), **localhost auth bypass**
  (A-3), **manual HTML sanitizer / DOMPurify** (frontend), and every other audit
  finding — each is its own change.
- **No behavior change for legitimate users**: successful uploads, successful
  logins under the threshold, and all authenticated flows are identical.

## Impact

| Area | Impact | Description |
|------|--------|-------------|
| `backend/requirements.txt` | Modified | `python-multipart` → `>=0.0.20,<0.1`; add `slowapi` (PR2). |
| `backend/app/main.py` (docs setup, L207-215; limiter registration) | Modified | Single env flag drives `docs_url`/`redoc_url`/`openapi_url`; register `Limiter` + 429 handler (PR2). |
| `backend/app/routers/administracion_compras.py` (`wipe_compras_endpoint`, L4726-4736) | Modified | Env-gate-404 before the existing permission guard. |
| `backend/app/api/endpoints/auth.py` (`login`, L48) | Modified | `@limiter.limit("10/minute")` keyed by `CF-Connecting-IP` (PR2). |
| New limiter module / key function | Added | `CF-Connecting-IP`-with-fallback key func + Redis-backed `Limiter` (PR2). |
| `backend/tests/...` | Added | docs-disabled-in-prod, wipe-404-in-prod, login-429-after-N tests. |
| Upload endpoints (20 sites) | No change | Same `UploadFile` contract; covered by re-run of existing tests. |
| Redis | New login-path dependency | The login path now consults Redis for rate counters (see Risks). |
| End users | No change | Legitimate uploads/logins/flows behave identically. |

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| **Redis becomes a hard dependency of the login path.** If Redis is down and the limiter is fail-closed, an infra outage would lock **everyone** out of login. | Med | **Decision: fail-OPEN.** If the Redis store is unreachable, the limiter must allow the request through and **log a warning** (do not raise). Rationale: a brute-force window during a Redis outage is far less damaging than a total login lockout for all users. Design/spec must pin the exact fail-open behavior (catch the storage error in the limiter path, log, allow). This is a documented, deliberate tradeoff. |
| `python-multipart` bump silently breaks an upload path. | Low | Re-run **all existing upload tests** (20 sites) after the bump before merging PR1; the app never calls multipart internals, only FastAPI `UploadFile`. |
| Rate limiter keys on a Cloudflare edge IP instead of the real client (would throttle all users behind one edge). | Low | Key strictly on `CF-Connecting-IP`; never trust `X-Forwarded-For`. Fallback to `request.client.host` only when the header is absent (dev/direct). |
| `10/minute` too aggressive and throttles a legitimate retry-heavy user. | Low | 10/min is ~3x a realistic human retry rate; expose as a tunable config so it can be raised without a code change if support reports friction. |
| Env-gate-404 accidentally applied to a route that production legitimately needs. | Low | Applied to exactly one route (`wipe-compras`, permission literally named "testing"); no prod workflow depends on it. Scope is a single function. |
| Test flakiness from shared limiter state across tests. | Med | Isolate/reset limiter (and Redis test key namespace) between tests via fixture teardown so the 429 test does not leak counters into others. |

## Success Criteria

1. **Item 1:** `requirements.txt` pins `python-multipart>=0.0.20,<0.1`; the full
   existing upload test set passes after the bump.
2. **Item 2:** a test asserts `app.openapi_url` (and docs/redoc URLs) are `None`
   when `ENVIRONMENT != "development"` and non-`None` in `development`.
3. **Item 3:** a test asserts `/api/testing/wipe-compras` returns **404** when
   `ENVIRONMENT` is set to `"production"` (via `monkeypatch.setattr(settings, ...)`),
   while the permission guard still governs the `development` path.
4. **Item 4:** a test hits `/api/auth/login` past the threshold and asserts a
   **429** on the over-limit attempt, with limiter state isolated per test.
5. **Fail-open verified:** a test (or documented design assertion) confirms that a
   Redis storage failure lets the login request proceed (allowed + warning logged),
   never a lockout.
6. **The entire existing backend suite stays green**
   (`cd backend && source venv/bin/activate && pytest`).
7. Both PRs stay well under the 400-line budget (each is a small, bounded diff).

## Approach — Rejected Alternatives

- **In-memory slowapi storage — REJECTED.** With 4 uvicorn workers each holding its
  own in-memory counter, a "10/minute" limit becomes effectively "40/minute"
  globally (and unpredictable, depending on which worker serves each request).
  Redis gives one shared, global counter across all workers. Redis is already a
  project dependency (SSE pub/sub), so this introduces no new dependency *category*.
- **Hand-rolled limiter — REJECTED.** A bespoke Redis token-bucket was considered to
  avoid a new library, but slowapi 0.1.10 compatibility with the pinned
  fastapi/starlette was verified (`pip install --dry-run`), so there is no reason to
  reinvent battle-tested throttling. slowapi is a thin, well-maintained wrapper over
  the `limits` library.
- **Three separate settings for docs/redoc/openapi — REJECTED.** Swagger and ReDoc
  both fetch the OpenAPI schema, so a single `ENVIRONMENT == "development"` flag
  gates all three; three flags would be redundant surface with no added control.
- **Return 403 (not 404) for `wipe-compras` — REJECTED.** 403 confirms the endpoint
  exists; the audit specifically wants production clients unable to distinguish it
  from a nonexistent route, so 404 is the correct code.
- **Fail-closed rate limiter — REJECTED.** Blocking login when Redis is down turns a
  storage outage into a total-authentication outage; fail-open with a logged warning
  is the deliberate choice (see Risks).

## Delivery

- **Two independent PRs to `main`** (per the decisions round):
  - **PR1:** items 1–3 (mechanical, no new dependency, low risk).
  - **PR2:** item 4 (new `slowapi` dependency + Redis-coupled login path, warrants
    more careful review).
- Strict TDD is active: `cd backend && source venv/bin/activate && pytest`.

## Next Phase

`sdd-spec` and `sdd-design` (can run in parallel). Spec formalizes the acceptance
criteria per item (version pin, docs-disabled contract, wipe-404 contract,
login-429 contract, fail-open contract). Design pins the exact limiter module
shape, the `CF-Connecting-IP`-with-fallback key function, the Redis fail-open error
handling, and the precise placement of the env-gate-404 relative to the permission
guard.
