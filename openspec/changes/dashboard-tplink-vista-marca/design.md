# Technical Design: TP-Link Brand-Facing Dashboard (Restricted Brand View)

> Change: `dashboard-tplink-vista-marca`
> Phase: design (the HOW at architectural level)
> Depends on: `proposal.md` (locked decisions 1-7)

This design defines the brand router and its endpoint set, the permission wiring
(seed migration + dependency gate), the server-side store-lock mechanism, the
margin-masking shape, the offset-exclusion strategy, the frontend page
architecture, and the TP-Link theming approach. All decisions are grounded in the
real codebase (verified files cited inline), not the skill examples — note the
skill tables use placeholder names (`rol_permiso_base`); the real tables are
`roles_permisos_base` and `usuarios_permisos_override`.

---

## 1. Architecture Overview

**Pattern**: a NEW, isolated brand router (`/dashboard-tplink/*`) that delegates to
the EXISTING query helpers of `dashboard_ml.py` and `ventas_ml.py`, but wraps every
endpoint with two guarantees the shared endpoints do NOT provide:

1. **Permission gate** — `Depends(require_permiso("dashboard_tplink.ver"))` →
   403 if absent (the shared `/dashboard-ml/*` endpoints are auth-only today).
2. **Store hard-lock** — the brand router NEVER reads `tiendas_oficiales`,
   `pm_ids`, or `marcas` from the request; it injects `tiendas_oficiales="2645"`
   server-side and passes `pm_ids=None` so the PM/marca scoping is bypassed.

```
Brand user (restricted account, override: dashboard_tplink.ver [+ .ver_ganancia])
        │  JWT
        ▼
ProtectedRoute permiso="dashboard_tplink.ver"   (frontend gate — UX only)
        │
        ▼
GET /api/dashboard-tplink/*   (NEW router, backend gate — the real boundary)
        │  Depends(require_permiso("dashboard_tplink.ver"))  → 403 if absent
        │  tiendas_oficiales := "2645"  (server-injected, client value ignored)
        │  pm_ids := None, marcas := None
        ▼
aplicar_filtros_comunes(...) / _construir_operaciones(...)   (EXISTING helpers, unchanged)
        │
        ▼
Response → margin fields masked server-side unless dashboard_tplink.ver_ganancia
```

### Router home: NEW file `backend/app/api/endpoints/dashboard_tplink.py`

Registered in `main.py` next to the existing dashboards
(`app.include_router(dashboard_tplink.router, prefix="/api", tags=["dashboard-tplink"])`,
after line 253). No edits to `dashboard_ml.py` or `ventas_ml.py`.

---

## 2. ADR-1 — Thin wrappers delegating to shared helpers (NOT duplicated handlers)

**Decision**: the brand endpoints are THIN wrappers. They import and call the
existing module-level helpers from `dashboard_ml.py`
(`aplicar_filtros_comunes`, the per-endpoint query builders) and from
`ventas_ml.py` (the operaciones query path), passing a forced store id and
`pm_ids=None`. The wrappers own ONLY: the permission dependency, the store
injection, and the margin masking.

**Why**:
- The query logic (timezone-aware date filters, `is_cancelled` exclusion, the
  `mlp_official_store_id` → `mla_id` subquery in `aplicar_filtro_tienda_oficial`,
  `dashboard_ml.py:78-105`) is non-trivial and already correct. Re-deriving it
  invites divergence.
- The store-lock and the permission gate live in EXACTLY ONE place (the wrapper),
  decoupled from the shared internal endpoints. A future refactor of
  `/dashboard-ml/*` cannot leak the brand scope, because the brand path forces
  `2645` itself.
- Boring, explicit, greppable. Mirrors the proposal's "clone-and-restrict".

**Rejected — duplicated handlers** (copy the full SQL into the brand module):
larger diff, two copies of the aggregation math to keep in sync, higher blast
radius. The only thing that legitimately differs per brand is the store lock and
masking, which the wrapper already isolates.

**Rejected — reuse `/dashboard-ml/*` with an injected scope dependency**
(proposal's rejected alternative, reaffirmed): would thread a "scope" object
through every shared endpoint and trust that no future param re-opens the store
filter. More coupling, harder to prove the lock holds.

### Helper reuse note (apply-phase detail)

The current per-endpoint query builders in `dashboard_ml.py` are inlined inside
each route function (e.g. `get_metricas_generales`, line 230). They are NOT yet
standalone callables. Two acceptable apply strategies, decided at apply time to
keep the diff bounded:

- **(a) Preferred** — extract the body of each needed `dashboard_ml` route into a
  module-level `def _<name>(db, *, fecha_desde, fecha_hasta, categorias,
  tiendas_oficiales, pm_ids, current_user) -> <Response>` helper that BOTH the
  existing route and the brand wrapper call. This keeps a single source of truth
  with zero behavior change to `/dashboard-ml/*` (the existing route becomes a
  one-line delegate). Tests for `/dashboard-ml/*` (if any) still pass unchanged.
- **(b) Fallback if extraction risks the existing route** — the brand wrapper
  re-implements the thin aggregation but STILL calls the shared
  `aplicar_filtros_comunes` / `aplicar_filtro_tienda_oficial`. The duplicated part
  is only the `func.sum(...)` projection list, which is stable.

Recommend (a); it satisfies the proposal's "reuse query logic" intent best. The
choice is local and does not change any other decision in this design.

---

## 3. Endpoint Set (concrete)

The brand page has exactly two tabs (Resumen + Detalle de Operaciones) and two
filters (date range + categoría). The endpoints below are the minimal set backing
that UI, cloned from the surfaces the page actually consumes.

| Brand endpoint | Backs | Cloned from | Notes |
|----------------|-------|-------------|-------|
| `GET /api/dashboard-tplink/metricas-generales` | Resumen KPIs | `dashboard_ml.py:230` | margin fields masked by `.ver_ganancia` |
| `GET /api/dashboard-tplink/por-categoria` | Resumen "por categoría" | `dashboard_ml.py:352` | margin masked |
| `GET /api/dashboard-tplink/por-dia` | Resumen daily chart | `dashboard_ml.py:440` | margin masked |
| `GET /api/dashboard-tplink/por-logistica` | Resumen logística breakdown | `dashboard_ml.py:398` | **offset_flex dropped** (see §5) |
| `GET /api/dashboard-tplink/top-productos` | Resumen top productos | `dashboard_ml.py:486` | margin masked |
| `GET /api/dashboard-tplink/categorias-disponibles` | Categoría filter options | `dashboard_ml.py:582` | store-locked to 2645 |
| `GET /api/dashboard-tplink/operaciones-con-metricas` | Detalle tab (paginated table) | `ventas_ml.py:540` | margin masked, **offset_flex dropped** |
| `GET /api/dashboard-tplink/exportar-operaciones` | Detalle Excel export | `ventas_ml.py:961` | store-locked; margin columns gated |

**Excluded by construction** (never cloned): `/dashboard-ml/por-marca`
(no marca breakdown for a single brand), `/dashboard-ml/marcas-disponibles`,
`/dashboard-ml/mis-marcas` (no marca selector), and anything backing the
Rentabilidad tab / rendimientos offsets (`TabRentabilidad.jsx`).

Every brand endpoint signature exposes ONLY: `fecha_desde`, `fecha_hasta`,
`categorias`, plus pagination params on operaciones. It does NOT declare
`tiendas_oficiales`, `pm_ids`, or `marcas` as `Query(...)` params — they cannot be
supplied by the client because they are not in the function signature.

### Permission gate placement

Use `dependencies=[Depends(require_permiso("dashboard_tplink.ver"))]` on each
route (the existing factory at `deps.py:105`). It returns the project-standard
403 `INSUFFICIENT_PERMISSIONS`. Do NOT use the legacy inline
`verificar_permiso(...)` pattern; the dependency factory is the current convention.

---

## 4. ADR-2 — Server-side store lock by construction

**Decision**: the store id is a module-level constant injected into the existing
`aplicar_filtro_tienda_oficial` helper, never read from the request.

```python
# dashboard_tplink.py
TPLINK_OFFICIAL_STORE_ID = "2645"  # TP-Link official store (dashboard_ml.py:84-87)

# inside every wrapper, ALWAYS:
tiendas_oficiales = TPLINK_OFFICIAL_STORE_ID   # never from Query(...)
pm_ids = None                                  # bypass PM marca scoping
marcas = None                                  # no marca filter
```

`aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, marcas=None,
categorias=categorias, tiendas_oficiales="2645", db=db)` then applies the existing
`mlp_official_store_id == 2645` subquery filter (`dashboard_ml.py:96-104`).

**Why by construction, not by validation**: there is no "reject if client sent a
store" branch to forget — the param simply does not exist on the endpoint. Even a
crafted `?tiendas_oficiales=57997` is ignored by FastAPI (extra query params are
dropped) and would have no binding inside the handler. This is the strongest form
of the lock: you cannot bypass a parameter that the server never reads.

**PM/marca scoping bypass**: the shared endpoints call
`aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)` which, for a
non-admin user with no `MarcaPM` assignments, would filter to
`marca == "__NINGUNA__"` and return nothing (`dashboard_ml.py:67-69`). The brand
wrappers MUST therefore SKIP `aplicar_filtro_marcas_pm` entirely (the brand sees
ALL marcas WITHIN store 2645, which is exactly TP-Link's catalog). The store
filter is the only scoping the brand view applies. This is a deliberate difference
from the shared path and a key apply-phase instruction.

---

## 5. ADR-3 — Margin masking shape: OMIT, not zero

**Decision**: when `dashboard_tplink.ver_ganancia` is ABSENT, the server OMITS the
sensitive margin fields from the response payload (they are not serialized at all),
rather than returning them as `0`.

Sensitive field group (masked together, per proposal decision 1):
`total_ganancia`, `total_costo`, `markup_porcentaje`, `total_comisiones`
(metricas-generales); `total_ganancia`, `markup_porcentaje` (por-categoria,
por-dia, top-productos); `costo_sin_iva`, `costo_total`, `comision_porcentaje`,
`comision_pesos`, `markup_porcentaje`, `monto_limpio` (operaciones — the cost and
margin columns).

**Mechanism**: each brand response model declares the sensitive fields as
`Optional[...] = None`. After building the full result, if the user lacks
`.ver_ganancia`, the wrapper sets those fields to `None` and the brand uses
`response_model_exclude_none=True` on the route so they are dropped from the JSON.
A masked metricas response therefore contains `total_ventas_ml`,
`cantidad_operaciones`, `cantidad_unidades`, `total_envios` — and NO
ganancia/costo/markup/comisiones keys at all.

**Why OMIT over ZERO**:
- A zeroed `markup_porcentaje: 0` is a *plausible real value* — the client cannot
  distinguish "masked" from "genuinely zero margin", which leaks ambiguity and
  risks a frontend treating it as real data. Absence is unambiguous: the key is
  gone, the frontend renders `***`.
- Zeroing still ships a number shaped like the real one; a bug that forgets to
  zero one field silently leaks it. With omission, a forgotten field is caught
  because the masked response's schema is explicitly the reduced set — the test
  asserts the keys are ABSENT.
- The proposal's hard requirement: "the client must never receive the real numbers
  when the permission is absent." Omission is the cleanest enforcement.

**Frontend mirror**: the page reads `puedeVerGanancia =
tienePermiso('dashboard_tplink.ver_ganancia')` and renders `***` wherever a
sensitive value would appear — identical to the existing
`DashboardMetricasML.jsx:28,949` pattern (`puedeVerGanancia ? formatear(...) :
'***'`). Because the field is also absent from the payload, the FE never has the
number even if a developer forgets a `***` guard.

**Excel export** (`exportar-operaciones`): when `.ver_ganancia` is absent, the
margin/cost COLUMNS are omitted from the workbook entirely (not written as 0 or
blank in a present column). Same rationale.

---

## 6. ADR-4 — Offsets excluded by construction (no permission unlocks them)

Offsets appear in these cloned source locations; each is excluded in the brand
clone:

| Source location | What it is | Brand treatment |
|-----------------|------------|-----------------|
| `DashboardMetricasML.jsx:976-991` | Offset Flex KPI block in metricsRow | NOT rendered — block omitted from brand page |
| `DashboardMetricasML.jsx:842-843` | `offset_flex` column in operaciones table | Column omitted from brand table |
| `DashboardMetricasML.jsx:1128-1129` | Logística offset line | Line omitted from brand logística card |
| `dashboard_ml.py:167,199,256,300` | `total_offset_flex` in metricas + logística responses | Field DROPPED from brand response models |
| `ventas_ml.py:532` | `offset_flex` in `OperacionConMetricasResponse` | Field DROPPED from brand operaciones model |

**By construction**: the brand response models simply do not declare
`total_offset_flex` / `offset_flex`. The wrapper does not project them (it omits
`func.coalesce(func.sum(MLVentaMetrica.offset_flex), 0)` from the select list, or
discards it after the shared query). The brand page JSX never references offset
fields. The Rentabilidad tab (where rendimientos offsets live,
`TabRentabilidad.jsx`) is not part of this view at all. No permission, present or
absent, can surface an offset — there is no code path that emits one.

---

## 7. ADR-5 — Permission wiring: Alembic seed migration mirroring `ver_ganancia`

**Decision**: a single new Alembic migration seeds both permissions into the
`permisos` catalog and assigns them to internal roles, mirroring
`20260306_add_permisos_ver_ganancia.py` exactly (verified pattern).

New file: `backend/alembic/versions/20260624_add_permisos_dashboard_tplink.py`

```python
revision = "20260624_permisos_dashboard_tplink"
down_revision = "20260624_recepcion_estado_controlado"  # current head (verified)
```

> Head check: `20260623_permiso_reescribir_lh` is superseded by
> `20260624_recepcion_estado_controlado` (the in-flight compras change). The new
> migration MUST chain after whatever is `alembic heads` at apply time. If the
> compras change merges/renames first, re-point `down_revision` accordingly at
> apply. Run `cd backend && alembic heads` before writing the file.

```python
PERMISOS = [
    ("dashboard_tplink.ver",
     "Ver dashboard TP-Link",
     "Acceso a la vista de marca TP-Link (datos no sensibles, tienda 2645)",
     "ventas_ml", 60, False),
    ("dashboard_tplink.ver_ganancia",
     "Ver ganancia TP-Link",
     "Ver montos de ganancia/markup/costos/comisiones en la vista TP-Link",
     "ventas_ml", 61, False),
]

# Internal visibility only. The BRAND user gets dashboard_tplink.ver via a
# per-user OVERRIDE (usuarios_permisos_override), NOT a role grant.
ROL_PERMISOS = {
    "ADMIN":   ["dashboard_tplink.ver", "dashboard_tplink.ver_ganancia"],
    "GERENTE": ["dashboard_tplink.ver", "dashboard_tplink.ver_ganancia"],
}
```

`upgrade()` / `downgrade()` are byte-for-byte the structure of the `ver_ganancia`
migration (idempotent `INSERT ... ON CONFLICT (codigo) DO NOTHING`, role assignment
via `CROSS JOIN ... ON CONFLICT DO NOTHING`; `downgrade` deletes from
`roles_permisos_base`, `usuarios_permisos_override`, then `permisos`).

**Brand-account provisioning is NOT in the migration** (proposal non-goal:
"the account is created/granted manually"). The TP-Link user receives
`dashboard_tplink.ver` (and optionally `.ver_ganancia`) through the existing
override flow (`PermisosService.agregar_override`, `permisos_service.py:141` /
the `/usuarios/{id}/permisos` UI). This keeps the sensitive disclosure a deliberate
manual act — see §9.

**Category choice**: `categoria="ventas_ml"` (an existing `CategoriaPermiso`,
`permiso.py:21`) so the two permissions render in the existing permissions panel
without a new category.

---

## 8. Frontend Architecture

**Decision**: a NEW page `frontend/src/pages/DashboardTPLink.jsx` + CSS Module
`DashboardTPLink.module.css`, forked from `DashboardMetricasML.jsx`, NOT a shared
parametrized component.

**Why fork, not share**: `DashboardMetricasML.jsx` carries internal-only logic
(store selector, PM filter, marca selector, Rentabilidad tab wiring, offset blocks)
that must NOT leak into the brand build even behind flags — the safest way to
guarantee an internal control never renders for the brand is for the code to not
exist on the brand page. A shared component with `if (isBrand)` guards risks a
future edit re-exposing an internal control. The fork is bounded (two tabs, two
filters) and the proposal explicitly green-lights a new page.

The forked page:
- Calls `/api/dashboard-tplink/*` (NOT `/dashboard-ml/*` or `/ventas-ml/*`).
- Renders ONLY: header (TP-Link branded), date-range + categoría filters,
  Resumen tab, Detalle de Operaciones tab.
- Removes: store selector, PM selector, marca selector, Rentabilidad tab,
  all offset blocks (§6), the `tiendas_oficiales` / `pm_ids` query plumbing.
- Margin masking: `const puedeVerGanancia =
  tienePermiso('dashboard_tplink.ver_ganancia')` → `***` everywhere a sensitive
  value would render (mirrors `DashboardMetricasML.jsx:28`).

**Routing** (`App.jsx`): new lazy/eager import + route
`<ProtectedRoute permiso="dashboard_tplink.ver"><DashboardTPLink /></ProtectedRoute>`
following the existing pattern (`App.jsx:126`). Path e.g. `/dashboard-tplink`.

**Sidebar** (`Sidebar.jsx`): a menu entry gated by
`tienePermiso('dashboard_tplink.ver')`. Because the brand account has ONLY this
permission, its sidebar shows only this entry — landing it directly on the page.
(The `SmartRedirect` at `App.jsx:119` should also be confirmed at apply to route a
brand-only user to `/dashboard-tplink` as their home; if it redirects by role, a
small permission-aware branch may be needed. Flag for apply, low risk.)

Stack constraints honored: React 18, Zustand, CSS Modules, design tokens. NO
Tailwind utilities, NO inline styles (except genuinely dynamic values like a
computed bar height), NO hardcoded colors.

---

## 9. ADR-6 — TP-Link theming via scoped token override (no design-system fork)

**Decision**: apply the TP-Link accent + logo + title by OVERRIDING design tokens
on a single wrapper element in the page's CSS Module, NOT by editing
`design-tokens.css` or forking Tesla components.

```css
/* DashboardTPLink.module.css */
.brandRoot {
  /* Scope-local override of the brand accent ONLY for this subtree. */
  --brand-primary: #0d7d3f;   /* TP-Link corporate green (example; confirm hex) */
  --brand-secondary: #0a6332;
  --brand-hover: #085029;
}
```

The page's root `<div className={styles.brandRoot}>` redefines `--brand-*`
locally; every descendant that composes Tesla classes
(`composes: btn-primary from '...buttons-tesla.css'`) automatically picks up the
TP-Link accent through the cascade, with ZERO edits to the shared stylesheet.

**Dark mode**: the override only touches the BRAND accent tokens, never the
semantic surface tokens (`--bg-primary`, `--text-primary`, `--border-color`),
which keep flowing from `[data-theme="dark"]` on `:root`. Therefore dark mode keeps
working untouched. If the chosen TP-Link green needs a different shade in dark mode,
add a `[data-theme="dark"] .brandRoot { --brand-primary: ...; }` rule scoped to the
module — still no shared-file edit.

**Logo + title**: rendered in the page header as a brand `<img>` (asset under
`frontend/src/assets/`) + an `<h1>` with the brand title, styled via the module.
No global header change.

**Why scoped override**: it gives full brand identity with a single low-risk CSS
file, cannot regress any other page (the override dies at the subtree boundary),
and respects the "no design-system fork, tokens only" rule.

**Rejected** — editing `design-tokens.css` `--brand-primary` globally (would
recolor the whole app) or forking Tesla button/table stylesheets (duplication,
maintenance burden, violates the skill's NON-NEGOTIABLE rules).

---

## 10. RECONFIRMED — Sensitive-data disclosure decision (do NOT silently change)

**Accepted decision (product owner, reaffirmed here):** TP-Link MAY be shown
ganancia $, markup %, costos, and comisiones for store 2645 — but ONLY when the
brand account is explicitly granted `dashboard_tplink.ver_ganancia`. With only
`dashboard_tplink.ver`, every margin figure is OMITTED server-side and rendered
`***` (§5).

This is a genuine business risk (exposing internal margin/negotiation data to an
external brand). The design encodes the **cheap, reversible safeguard**: the second
permission is a SEPARATE manual override. To withhold all margins, simply do NOT
grant `dashboard_tplink.ver_ganancia` to the brand user — the page works fully with
margins masked, and no code change is needed to reverse the disclosure. The default
brand provisioning SHOULD grant only `dashboard_tplink.ver`; granting
`.ver_ganancia` is an explicit, auditable second step (`usuarios_permisos_override`
records `otorgado_por_id` + `motivo`, `permiso.py:104-105`).

No silent change: this restates the proposal's accepted decision and its rollback;
it does not alter it.

---

## 11. Testing Approach (strict TDD active)

Test runner: `cd backend && pytest tests/ -v --tb=short`. Frontend has no runner
(manual verification). Follow the existing integration-test pattern in
`tests/integration/test_consultas_ranking_scope.py` (real `db` fixture seeding a
`Rol` + `Usuario`, JWT via `create_access_token`, permission asserted through the
seeded grants/overrides or a `PermisosService` patch).

New test file: `backend/tests/integration/test_dashboard_tplink.py`. Write these
RED-first, one behavior at a time:

1. **Permission gate (403/200)** — user WITHOUT `dashboard_tplink.ver` →
   403 `INSUFFICIENT_PERMISSIONS` on each brand endpoint; user WITH it → 200.
2. **Store lock ignores client param** — request
   `/dashboard-tplink/metricas-generales?tiendas_oficiales=57997` returns ONLY
   store-2645 data (assert the executed query binds store `2645` and that the
   `57997` value has NO effect — e.g. by seeding 2645 + 57997 metrics and asserting
   the response reflects only 2645, or by inspecting the `mlp_official_store_id`
   filter binding). The param is not even declared, so this proves construction.
3. **PM/marca scoping bypass** — a brand user with NO `MarcaPM` rows still gets
   store-2645 data (asserts the wrapper SKIPS `aplicar_filtro_marcas_pm`; without
   the bypass the shared path would return empty).
4. **Margin masking — permission absent** — user with `dashboard_tplink.ver` but
   NOT `.ver_ganancia`: assert the response JSON does NOT contain the sensitive
   keys (`total_ganancia`, `total_costo`, `markup_porcentaje`, `total_comisiones`
   for metricas; the cost/margin keys for operaciones). Assert ABSENCE, not zero.
5. **Margin present — permission granted** — user with BOTH permissions: sensitive
   keys present with real values.
6. **Offsets absent always** — neither permission surfaces `total_offset_flex` /
   `offset_flex`; assert those keys are absent from metricas, logística, and
   operaciones responses for BOTH permission levels.
7. **SUPERADMIN resolves** — `es_superadmin` user → 200 with full (unmasked) data
   (the `tiene_permiso` SUPERADMIN short-circuit, `permisos_service.py:104`).

Migration test (mirror `tests/unit/test_permisos_referenciados.py` if it asserts
catalog presence): assert `dashboard_tplink.ver` and `dashboard_tplink.ver_ganancia`
exist in the catalog after `upgrade()` and are removed after `downgrade()`.

TDD order: start with the gate (1) and masking absence (4) — they are the security
contract — then store lock (2), bypass (3), offsets (6), then the positive paths
(5, 7).

### Alembic migration step (apply)

```bash
cd backend
alembic heads                      # confirm current head → set down_revision
# (write 20260624_add_permisos_dashboard_tplink.py)
alembic upgrade head               # apply
alembic downgrade -1 && alembic upgrade head   # verify reversibility
```

---

## 12. Delivery & Review Workload Footprint

Branch `develop`; PR to `main`. Rough changed-line estimate (informs the
chained-PR decision at tasks time):

| Area | New/Modified | ~Lines |
|------|--------------|--------|
| `dashboard_tplink.py` (router + 8 wrappers + response models) | New | ~280-360 |
| `20260624_add_permisos_dashboard_tplink.py` | New | ~80 |
| `main.py` (register router) | Modified | ~1 |
| `dashboard_ml.py` helper extraction (ADR-1 option a, if taken) | Modified | ~40 (refactor, behavior-neutral) |
| `DashboardTPLink.jsx` | New | ~600-800 (fork of a ~1130-line page, trimmed) |
| `DashboardTPLink.module.css` | New | ~150-300 |
| `App.jsx` (route) + `Sidebar.jsx` (entry) + `SmartRedirect` tweak | Modified | ~10 |
| `tests/integration/test_dashboard_tplink.py` | New | ~250-350 |

Backend (router + migration + tests) is a cohesive, independently shippable slice
(~700-850 lines incl. tests). The frontend fork is the larger, separable slice
(~750-1100 lines). **Total comfortably exceeds the 400-line single-PR budget** →
the Review Workload Forecast should flag **chained/stacked PRs**: PR #1 = backend
(permissions migration + brand router + tests, fully testable in isolation),
PR #2 = frontend page + routing + sidebar + theming (manual verification). This
split is natural because the backend is the security boundary and is verifiable on
its own before any UI exists.

---

## 13. Out of Scope (reaffirmed)

No changes to `DashboardMetricasML.jsx`, `/dashboard-ml/*`, or `/ventas-ml/*`
behavior (ADR-1 option (a) is a behavior-neutral extraction, not a behavior
change). No Rentabilidad tab, no offsets, no store/PM/marca selectors, no
self-service brand provisioning. The auth-only exposure of the existing
`/dashboard-ml/*` endpoints is a noted follow-up audit item, NOT fixed here.
