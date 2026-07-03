# Design: Security Quick Wins — June Audit Week-1 Hardening

> Change: `security-quick-wins`
> Backend: FastAPI 0.104.1 / Starlette 0.27.0 / Pydantic v2 / SQLAlchemy 2.0.
> Delivered as **two independent PRs to `main`**. This document pins the exact
> technical shape of each change, verified against the live code on
> `fix/prearmado-erp-session` @ 2026-07-02 (not against line numbers from prior
> phases). Every file/line reference below was re-read from source.

---

## 0. Architecture Overview

No new architectural layer is introduced. Both PRs are **surgical hardening** on
the existing FastAPI app singleton (`app/main.py`) plus two endpoint modules. The
only genuinely *new* structural element is a small rate-limiting module for PR2
(`app/core/rate_limit.py`) that owns the `Limiter`, the key function, and the
fail-open exception handler — kept out of `main.py` so the wiring in `main.py`
stays declarative (import + 3 lines).

Layering / boundaries:

- **Config boundary** (`app/core/config.py`): all tunables (`ENVIRONMENT`,
  `REDIS_URL`, new `LOGIN_RATE_LIMIT`, new `RATE_LIMIT_STORAGE_URI`) live in
  `Settings`. No magic strings in handlers.
- **Error boundary** (`app/core/exceptions.py`): every error response — including
  the new 404 gate and the new 429 — MUST flow through the centralized envelope
  `{"error": {"code", "message"}}`. No endpoint invents its own error body.
- **App-wiring boundary** (`app/main.py`): docs-URL computation and limiter
  registration are the only edits; routers are untouched.
- **Rate-limit boundary** (`app/core/rate_limit.py`, PR2 only): isolates the
  slowapi dependency so a future swap (or removal) touches one file.

Data flow is unchanged for every successful request. The only new runtime edge is
the login path consulting Redis for a counter (PR2), designed to **fail open**.

---

## PR1 — Mechanical Hardening (items 1–3)

### 1. `python-multipart` pin bump

**File:** `backend/requirements.txt:40`

```diff
-python-multipart==0.0.6
+python-multipart>=0.0.20,<0.1
```

- Verified: `fastapi==0.104.1` (line 16) declares `python-multipart` only as an
  optional extra with `>=0.0.5` and **no upper bound**, so `>=0.0.20,<0.1` is
  compatible. No other pin in `requirements.txt` references multipart.
- No app-code change. The codebase only touches multipart via FastAPI
  `UploadFile`/`File(...)` (20 sites per exploration); it never imports
  `multipart` internals (e.g. the removed `parse_options_header`). The API
  surface FastAPI uses (`multipart.multipart.parse_options_header` is called
  *inside Starlette*, and Starlette 0.27.0 already tolerates the new
  python-multipart line — no starlette bump needed).
- **Regression strategy:** re-run the full existing suite (which exercises upload
  endpoints such as `test_compras_adjuntos_endpoints.py`). No new test for item 1;
  the bump is covered by existing upload tests staying green.

**ADR-1 — pin as a range, not a new exact pin.**
Rejected `python-multipart==0.0.20` (exact) because the file already mixes exact
pins and ranges (`PyJWT>=2.8.0`), and the CVE fix is stable across the `0.0.x`
line; `>=0.0.20,<0.1` closes the CVE while absorbing future `0.0.x` patch
releases without a churny follow-up PR. `<0.1` guards against an unvetted `0.1`
minor.

---

### 2. Env-gate the OpenAPI docs

**File:** `backend/app/main.py:207-215` (the `FastAPI(...)` constructor).

Current (verified):

```python
app = FastAPI(
    title="Pricing API",
    description="API para gestión de precios de productos",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
```

**Design — a pure helper + spread into the constructor.** Introduce a module-level
pure function (in `main.py`, above the `app = FastAPI(...)` call) that maps an
environment string to the three URL kwargs:

```python
def _docs_urls(environment: str) -> dict[str, str | None]:
    """Return docs/redoc/openapi URL kwargs, disabled outside development.

    Passing None to FastAPI disables the corresponding route entirely. One flag
    gates all three because Swagger UI and ReDoc both fetch openapi_url.
    """
    if environment == "development":
        return {
            "docs_url": "/api/docs",
            "redoc_url": "/api/redoc",
            "openapi_url": "/api/openapi.json",
        }
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}
```

```python
app = FastAPI(
    title="Pricing API",
    description="API para gestión de precios de productos",
    version="1.0.0",
    lifespan=lifespan,
    **_docs_urls(settings.ENVIRONMENT),
)
```

- `settings.ENVIRONMENT` defaults to `"production"` (`config.py:26`) → **fail-closed
  by default**: any unset/missing env disables docs.
- Passing `None` for `openapi_url` alone would already disable `/api/docs` and
  `/api/redoc` (both fetch the schema); we set all three to `None` explicitly for
  intent-clarity and defense-in-depth.

**Audit of other docs-URL references in `main.py`:** none. Grepped — there are no
custom `/api/docs` / `/api/redoc` / `/api/openapi.json` routes, no
`get_openapi()` override, no `get_swagger_ui_html` mount, and the startup log
(`logger.info("Pricing API started ...", app.version, settings.ENVIRONMENT)`,
line 143) does not print the docs URLs. So gating the constructor is sufficient
and complete.

**ADR-2 — pure `_docs_urls(env)` helper instead of inline ternaries.**
The helper is a pure, side-effect-free function of `environment`, which makes it
**directly unit-testable without constructing the app or a TestClient** — this
sidesteps the import-time gotcha described in §4. Rejected inline
`docs_url="/api/docs" if _flag else None` (×3) because it is not testable in
isolation: `app.openapi_url` is frozen at import time (see §4), so a monkeypatch
after import cannot re-derive it.

---

### 3. `wipe-compras` returns 404 outside development

**File:** `backend/app/routers/administracion_compras.py:4726-4736`.

Current (verified) — guarded **only** by a permission dependency:

```python
@router.post(
    "/testing/wipe-compras",
    response_model=WipeComprasResponse,
    summary="[TESTING] Limpiar todas las tablas del módulo compras",
    tags=["Testing"],
)
def wipe_compras_endpoint(
    body: WipeComprasRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.wipe_compras_testing")),
) -> WipeComprasResponse:
```

#### 3.1 Placement decision — route-level dependency (NOT first-line-of-handler)

Three candidate placements were evaluated:

| Placement | Runs before permission check? | Runs before body 422? | Leaks existence? |
|---|---|---|---|
| First line of handler body | ❌ No — `require_permiso` (a `Depends`) resolves first | ❌ No | **Yes** — an unauthorized prod caller gets 401/403, and a bad body gets 422, both confirming the route exists |
| Parameter-level `Depends` placed first | ✅ Yes, if declared before `_user` | ✅ Yes | No, but ordering is implicit in signature position |
| **Route-decorator `dependencies=[...]`** | ✅ **Guaranteed** | ✅ **Guaranteed** | **No** |

**Chosen: route-decorator-level dependency.** FastAPI inserts
`dependencies=[...]` at the **front** of the dependant's dependency list
(`APIRoute` prepends them), so they resolve **before** any parameter-level
dependency (`require_permiso`, `get_db`) **and before body validation** (body
fields are validated after the dependency loop inside `solve_dependencies`). A
dependency that raises `HTTPException` short-circuits immediately, so neither the
403 (missing permission) nor the 422 (bad body) can ever surface in production —
the route is indistinguishable from a nonexistent one.

First-line-of-handler is **rejected**: `require_permiso` and the body validator
run *before* the handler body, so it leaks the route via 401/403/422.

Implementation:

```python
# near the top of administracion_compras.py (module-level dependency)
from fastapi import HTTPException
from app.core.config import settings

def _require_development_env() -> None:
    """Env-gate-404: hide testing-only routes outside development.

    Raises a bare 404 (no custom detail) so the response is byte-identical to the
    framework's response for a nonexistent route — production clients cannot tell
    this endpoint exists. Defense-in-depth: layered ON TOP OF the permission
    guard, which is retained.
    """
    if settings.ENVIRONMENT != "development":
        raise HTTPException(status_code=404)
```

```python
@router.post(
    "/testing/wipe-compras",
    response_model=WipeComprasResponse,
    summary="[TESTING] Limpiar todas las tablas del módulo compras",
    tags=["Testing"],
    dependencies=[Depends(_require_development_env)],   # ← env-gate-404, runs FIRST
)
def wipe_compras_endpoint(
    body: WipeComprasRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permiso("administracion.wipe_compras_testing")),
) -> WipeComprasResponse:
    ...  # body unchanged
```

The permission dependency (`administracion.wipe_compras_testing`) **stays** — the
env-gate is additive, not a replacement.

#### 3.2 Indistinguishability — the crux

The audit's intent is that a production client **cannot distinguish** the gated
route from a genuinely unknown route. This requires the 404 **body**, not just the
status, to match.

Verified error-handling reality in this app:

- `main.py:218` registers `app.add_exception_handler(HTTPException, http_exception_handler)`
  where `HTTPException` is `fastapi.HTTPException`.
- `http_exception_handler` (`app/core/exceptions.py:112`) normalizes: a **string**
  `detail` → `{"error": {"code": _status_to_code(404), "message": detail}}` →
  for 404, `code="NOT_FOUND"`, `message="Not Found"` (the phrase FastAPI assigns
  when `HTTPException(404)` is raised with no `detail`).

**Design rule:** raise a **bare `HTTPException(status_code=404)` with NO custom
detail** (using the same `fastapi.HTTPException` the app already raises). A custom
message (e.g. via `api_error(404, ErrorCode.NOT_FOUND, "...")`) would change
`message` and thereby **leak** the route. Bare-404 is mandatory.

Because there is a known subtlety in how Starlette vs FastAPI `HTTPException`
subclasses are matched by exception handlers for *unmatched* routes, the design
does **not** assert an exact body literal in isolation. Instead the **acceptance
test compares against a control** (see §4.3): the gated response MUST equal the
response for a truly-unknown route (same status, same JSON body, same
content-type). This makes indistinguishability self-verifying and immune to
handler-MRO nuances.

**ADR-3 — establish an `env-gate-404` pattern, distinct from the existing
`env-gate-403` at `auth.py:99-103`.**
`/auth/register` intentionally returns **403** (`REGISTRATION_DISABLED`) because it
is a *known-public* route whose existence is not secret. `wipe-compras` is the
opposite: its existence must be hidden, so **404** with an indistinguishable body
is correct. Two different gates for two different threat models; both are
retained.

---

## PR2 — Login Rate Limiting (item 4)

### 5. slowapi integration

**New dependency** — `backend/requirements.txt` (add near `redis==5.0.1`, line 42):

```
slowapi==0.1.10
```

Compat re-confirmed from the decisions round: slowapi 0.1.10 pulls
`limits`, `Deprecated`, `wrapt` and does **not** touch pinned `fastapi==0.104.1`
/ `starlette==0.27.0`.

**New module — `backend/app/core/rate_limit.py`** (isolates slowapi so `main.py`
wiring is 3 lines and a future swap touches one file):

[content truncated for length — see the original design.md for full content]

