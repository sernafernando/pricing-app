# Tasks — dashboard-tplink-vista-marca

Generated: 2026-06-24
Spec: `openspec/changes/dashboard-tplink-vista-marca/specs/`
Design: `openspec/changes/dashboard-tplink-vista-marca/design.md`
TDD mode: **STRICT** (backend) — every impl task is preceded by its RED test task.
Frontend: no test runner — manual verification steps noted per task.

Delivery: **Chained PRs** (two slices)
- PR #1 — Backend security slice (permissions migration + brand router + tests)
- PR #2 — Frontend slice (page + routing + sidebar + theming) — targets `develop`, merges after PR #1 is merged

Chain strategy: **stacked-to-main** (each PR targets `main` independently via `develop`)

---

## Out of Scope (explicit)

- `GET /dashboard-tplink/por-marca` — excluded by construction (single-brand view, pointless)
- Excel/CSV export endpoint — v1 out of scope
- Pagination — all endpoints return full result sets
- Rentabilidad tab, rendimientos offsets — never in scope
- `dashboard_tplink.ver_ganancia` brand-user pre-provisioning — operational step, not in migration
- Fixing the pre-existing auth-only gap on `/dashboard-ml/*` — separate audit item
- Editing `DashboardMetricasML.jsx` behavior or any `/dashboard-ml/*` / `/ventas-ml/*` route

---

## Alembic Head Pre-Check (MANDATORY before writing migration)

Run `cd backend && alembic heads` at apply time. The current `down_revision` placeholder
in design is `20260624_recepcion_estado_controlado`. Re-confirm the actual head before
generating the migration file and update `down_revision` accordingly. This is task T-01.

---

## PR #1 — Backend Security Slice

Branch: `feat/dashboard-tplink-backend`
Target: `develop` → PR to `main`
Dependency: none (ships independently)

---

### Phase 1-A — Alembic Migration (sequential)

#### [x] T-01 · PRE · Verify Alembic head before migration

**Spec**: Permission Model — migration seeding  
**What**: Run `cd backend && alembic heads` and record the current revision string.
Update the `down_revision` in the migration file to match exactly.
If `20260624_recepcion_estado_controlado` is NOT the head (e.g. it merged with a
different name or a new migration exists), adjust accordingly before writing T-02.  
**Files**: none (diagnostic step)  
**Sequential**: must complete before T-02.

---

#### [x] T-02 · IMPL · Alembic migration — seed permissions + role assignments

**Spec**: Permission Model §seed migration, §role assignment  
**Design**: §7 ADR-5  
**File**: `backend/alembic/versions/20260624_add_permisos_dashboard_tplink.py` (new)  
**What**: Create a migration that:
1. Seeds `dashboard_tplink.ver` and `dashboard_tplink.ver_ganancia` into `permisos`
   table (`categoria="ventas_ml"`, `orden=60`/`61`, `requiere_superadmin=False`).
   Use `INSERT ... ON CONFLICT (codigo) DO NOTHING` (idempotent, mirrors
   `20260306_add_permisos_ver_ganancia.py` pattern).
2. Assigns both permissions to ADMIN and GERENTE roles via `roles_permisos_base`
   (`CROSS JOIN ... ON CONFLICT DO NOTHING`).
3. `downgrade()` removes from `roles_permisos_base`, `usuarios_permisos_override`,
   then `permisos` — same teardown order as the `ver_ganancia` migration.

**Commit message**: `feat(permisos): seed dashboard_tplink.ver and .ver_ganancia, assign to ADMIN/GERENTE`

**Depends on**: T-01 (head confirmed).

---

#### [x] T-03 · RED · Test — migration catalog presence

**Spec**: Permission Model — scenario "Migration seeds both permissions"  
**File**: `backend/tests/unit/test_dashboard_tplink_permisos.py` (new, or extend
`tests/unit/test_permisos_referenciados.py` if it covers catalog assertions)  
**What**: Write failing tests that assert:
- After `upgrade()`, exactly two rows matching `codigo LIKE 'dashboard_tplink.%'`
  exist in `permisos`.
- After `downgrade()`, those rows are gone.
- Both ADMIN and GERENTE have the permissions in `roles_permisos_base` after upgrade.

All tests must FAIL (no migration applied yet in isolation) before T-02 is run.  
**Depends on**: T-02 (migration file exists to import/test against).

---

### Phase 1-B — Brand Router (sequential after Phase 1-A)

#### [x] T-04 · RED · Integration test skeleton — permission gate (403/401/200)

**Spec**: Permission Model §Route Access Gate, §scenarios 401/403/200  
**Design**: §11 TDD §1  
**File**: `backend/tests/integration/test_dashboard_tplink.py` (new)  
**What**: Write failing tests (RED) for the permission gate contract:
- `test_unauthenticated_returns_401` — no JWT → 401 on `GET /api/dashboard-tplink/metricas-generales`
- `test_no_permission_returns_403` — valid JWT, user without `dashboard_tplink.ver` → 403
- `test_with_ver_permission_returns_200` — valid JWT, user WITH `dashboard_tplink.ver` → 200
- `test_all_endpoints_gate_403_without_permission` — parametrize across all 6
  brand endpoints to assert 403 for a user lacking `.ver`

Mock / fixture strategy: mirror `tests/integration/test_consultas_ranking_scope.py`
(seed a `Rol` + `Usuario`, JWT via `create_access_token`, permission set via
`PermisosService.agregar_override` or direct DB seed).

All tests must FAIL before the router is created (T-05).

---

#### [x] T-05 · IMPL · Brand router — file scaffold + response models + store lock constant

**Spec**: API Surface — §Dedicated Brand Router, §accepted params, §response models  
**Design**: §1 architecture, §3 endpoint set, §4 ADR-2 store lock  
**File**: `backend/app/api/endpoints/dashboard_tplink.py` (new)  
**What**:
1. Define module constant `TPLINK_OFFICIAL_STORE_ID = "2645"`.
2. Declare all response model classes (Pydantic v2 `ConfigDict`):
   - `MetricasGeneralesTPLinkResponse` — margin fields `Optional[Decimal] = None`; NO `offset_flex`/`total_offset_flex`
   - `VentaPorCategoriaTPLinkResponse`
   - `VentaPorLogisticaTPLinkResponse` — NO offset field
   - `VentaDiariaTPLinkResponse`
   - `TopProductoTPLinkResponse`
   - `OperacionTPLinkResponse` — margin fields optional; NO `offset_flex`
   - `CategoriasDisponiblesResponse` (or just `List[str]`)
3. Create the `router = APIRouter()` instance.
4. Stub each of the 6 endpoints as `raise HTTPException(status_code=501)` so the
   file imports cleanly and the gate tests can run.
5. Register the router in `main.py` after line ~253:
   `app.include_router(dashboard_tplink.router, prefix="/api", tags=["dashboard-tplink"])`

**Commit message**: `feat(dashboard-tplink): scaffold brand router, response models, store-lock constant`

**Depends on**: T-04 (tests exist to target).

#### Verify T-04 goes GREEN after T-05 (gate tests pass because dependency is wired).

---

#### [x] T-06 · RED · Integration tests — store lock ignores client param + PM bypass

**Spec**: Store Lock spec, API Surface §scenarios  
**Design**: §4 ADR-2, §11 TDD §2 and §3  
**File**: `backend/tests/integration/test_dashboard_tplink.py` (extend)  
**What**:
- `test_store_lock_ignores_client_param` — seed metrics for store 2645 AND store 57997;
  call `GET /api/dashboard-tplink/metricas-generales?tiendas_oficiales=57997`; assert
  response reflects ONLY store-2645 data (57997 data absent from aggregates).
- `test_pm_marca_bypass_returns_data_without_marcapm_rows` — brand user has NO
  `MarcaPM` assignment; verify response contains store-2645 data (not empty);
  confirms `aplicar_filtro_marcas_pm` is skipped.
- `test_extra_query_param_silently_ignored` — any extra unknown param does not
  cause 422 or affect result.

All must FAIL before T-07.

---

#### [x] T-07 · IMPL · Brand router — implement all 7 endpoint handlers (thin wrappers; operaciones added in follow-up commit)

**Spec**: API Surface — all endpoint requirements  
**Design**: §2 ADR-1 helper extraction, §3 endpoint set, §4 store lock, §5 margin masking  
**File**: `backend/app/api/endpoints/dashboard_tplink.py`  
**What**: Implement the 6 endpoint handlers as thin wrappers:
1. **Extract helpers from `dashboard_ml.py`** (ADR-1 option a) or use fallback
   strategy if extraction risks the existing route (decision made at apply based on
   inspection):
   - Extract query body of `get_metricas_generales`, `por_categoria`, `por_dia`,
     `por_logistica`, `top_productos`, `categorias_disponibles` into module-level
     `_<name>` helpers in `dashboard_ml.py`. Each existing route becomes a one-line
     delegate. ZERO behavior change to `/dashboard-ml/*`.
   - Similarly for `operaciones-con-metricas` in `ventas_ml.py`.
2. Each brand handler:
   - Injects `dependencies=[Depends(require_permiso("dashboard_tplink.ver"))]`
   - Sets `tiendas_oficiales = TPLINK_OFFICIAL_STORE_ID` (never from Query)
   - Sets `pm_ids = None`, `marcas = None`
   - Calls the extracted helper
   - Applies margin masking: if `not PermisosService.tiene_permiso(current_user, "dashboard_tplink.ver_ganancia")`, set margin fields to `None`
   - Route decorator uses `response_model_exclude_none=True`
3. `GET /dashboard-tplink/metricas-generales` — response excludes `total_offset_flex`
4. `GET /dashboard-tplink/por-logistica` — response excludes `total_offset_flex`
5. `GET /dashboard-tplink/operaciones` — `offset_flex` NOT in response model; margin gated
6. `GET /dashboard-tplink/categorias-disponibles` — store-locked, no margin

**Commit message**: `feat(dashboard-tplink): implement 6 brand endpoint wrappers with store lock and margin masking`

**Depends on**: T-06 (tests exist to target).

#### Verify T-06 goes GREEN after T-07.

---

#### [x] T-08 · RED · Integration tests — margin masking (absent keys, not zero)

**Spec**: Permission Model §Margin Gate; API Surface margin scenarios  
**Design**: §5 ADR-3 (OMIT not zero)  
**File**: `backend/tests/integration/test_dashboard_tplink.py` (extend)  
**What**:
- `test_margin_absent_when_no_ver_ganancia` — user WITH `.ver` only; assert
  `total_ganancia`, `markup_porcentaje`, `total_costo`, `total_comisiones` are
  **ABSENT** from `metricas-generales` JSON (not null, not zero — key must not exist
  due to `response_model_exclude_none=True`).
- `test_margin_present_when_ver_ganancia_granted` — user WITH both permissions;
  assert those keys ARE present with non-null values (given seeded data).
- `test_operaciones_margin_absent` — user `.ver` only; each row in `operaciones`
  response lacks `comision_porcentaje`, `comision_pesos`, `costo_sin_iva`,
  `costo_total`, `markup_porcentaje`.
- `test_operaciones_margin_present` — user with both; those keys present.

All must FAIL before T-09 (masking not yet implemented).

---

#### [x] T-09 · RED · Integration tests — offset absence (unconditional)

**Spec**: API Surface §No Offset Field; Design §6 ADR-4  
**File**: `backend/tests/integration/test_dashboard_tplink.py` (extend)  
**What**:
- `test_offsets_absent_from_metricas` — assert `total_offset_flex` NOT in metricas response at any permission level.
- `test_offsets_absent_from_logistica` — assert `total_offset_flex` NOT in por-logistica response.
- `test_offsets_absent_from_operaciones` — assert `offset_flex` NOT in any operaciones row.
- Parametrize across both permission levels (`.ver` only and `.ver` + `.ver_ganancia`).

All must FAIL before T-07 is complete (or add as regression assertions alongside T-08).

---

#### [x] T-10 · RED · Integration tests — SUPERADMIN full access

**Spec**: Permission Model §SUPERADMIN scenario  
**Design**: §11 TDD §7  
**File**: `backend/tests/integration/test_dashboard_tplink.py` (extend)  
**What**:
- `test_superadmin_gets_200_and_full_data` — `es_superadmin=True` user → 200 with
  all margin keys present (validates the `tiene_permiso` SUPERADMIN short-circuit).

Must FAIL until router is live (handler not yet returning 200 for superadmin).

---

> **T-08, T-09, T-10 should go GREEN once T-07 is complete.** Run full suite:
> `cd backend && pytest tests/ -v --tb=short`

---

#### [x] T-11 · VERIFY · Run full backend test suite; confirm all T-04 through T-10 pass

**What**: `cd backend && pytest tests/integration/test_dashboard_tplink.py -v --tb=short`
then `cd backend && pytest tests/ -v --tb=short` to confirm no regressions.  
**Acceptance**: all new tests GREEN, no existing test regressions.

---

#### [x] T-12 · VERIFY · Alembic round-trip check

**Design**: §11 migration step  
**What**:
```bash
cd backend
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```
Confirm clean upgrade, clean downgrade (no FK errors), clean re-upgrade.

---

## PR #1 Boundary

Work units in PR #1:
1. Alembic migration commit (T-02 + T-03)
2. Router scaffold + response models (T-05, includes main.py registration)
3. Gate + store-lock + PM-bypass tests + handler implementations (T-04, T-06, T-07)
4. Margin masking + offset tests (T-08, T-09, T-10)
5. SUPERADMIN test (T-10)

PR #1 is fully reviewable and testable in isolation. CI runs pytest. No frontend required.

---

## PR #2 — Frontend Slice

Branch: `feat/dashboard-tplink-frontend`
Target: `develop` → PR to `main` (depends on PR #1 merged so the backend API exists)

---

### Phase 2-A — Theming foundation (sequential)

#### [x] T-13 · IMPL · CSS Module + brand token (`--tplink-accent`)

**Spec**: Frontend view §TP-Link branding  
**Design**: §9 ADR-6 scoped token override  
**File**: `frontend/src/pages/DashboardTPLink.module.css` (new)  
**What**:
1. Create the CSS Module. Define `.brandRoot` as the single token-override scope:
   ```css
   .brandRoot {
     --tplink-accent: #4ACBD6;         /* TP-Link teal — one-line swap point */
     --brand-primary: #4ACBD6;
     --brand-secondary: #3ab3be;
     --brand-hover: #2d9aa5;
   }
   [data-theme="dark"] .brandRoot {
     --tplink-accent: #4ACBD6;         /* same teal holds in dark — adjust if needed */
     --brand-primary: #4ACBD6;
   }
   ```
2. Define layout classes: `.pageHeader`, `.brandLogo`, `.brandTitle`, `.tabContainer`,
   `.filterBar`, `.kpiGrid`, `.chartSection`, `.tableSection`.
3. NO hardcoded hex anywhere except inside the `--tplink-accent` / `--brand-*`
   custom property declarations. Every descendant class uses `var(--tplink-accent)`
   or composes from Tesla tokens (`var(--bg-primary)`, `var(--text-primary)`, etc.).
4. Dark mode: only override the brand accent tokens in `[data-theme="dark"] .brandRoot`.
   Surface tokens keep flowing from ThemeContext.

**Commit message**: `feat(dashboard-tplink): brand CSS module with --tplink-accent token scope`

**Manual verification**: open the page in light and dark mode, confirm teal accent renders, confirm other pages are unaffected.

---

### Phase 2-B — Page component (sequential, depends on T-13)

#### [x] T-14 · IMPL · `DashboardTPLink.jsx` — page scaffold (header + filters + tab shell)

**Spec**: Frontend view §page structure, §route, §filters  
**Design**: §8 frontend architecture  
**File**: `frontend/src/pages/DashboardTPLink.jsx` (new)  
**What**: Create the page component as a fork of `DashboardMetricasML.jsx`, stripped to:
1. Imports: `{ useState, useEffect }`, Zustand auth store, `usePermisos()`, lucide-react
   icons, `styles from './DashboardTPLink.module.css'`, axios from `services/api.js`.
2. Remove from the fork (do NOT port): store selector, PM selector, marca selector,
   Rentabilidad tab, ALL offset blocks, `tiendas_oficiales`/`pm_ids`/`marcas` query
   params, `TabRentabilidad.jsx` import, `por-marca` API call.
3. Permission guards:
   - `const { tienePermiso } = usePermisos()`
   - `const puedeVerGanancia = tienePermiso('dashboard_tplink.ver_ganancia')`
4. Page header: render `frontend/public/brand/tplink-logo-white.png` as `<img>` with
   `alt="TP-Link"` inside a colored header div using `var(--tplink-accent)` as
   background (or dark variant). This file is ALREADY in the repo — reference it as
   `/brand/tplink-logo-white.png` (public path).
5. Date range filter + categoría dropdown (calls `GET /api/dashboard-tplink/categorias-disponibles`).
6. Two tab buttons: **Resumen** and **Detalle de Operaciones**.
7. State: `activeTab`, `fechaDesde`, `fechaHasta`, `categoriasFiltro`, loading flags.
8. Stub tab content panels: `{activeTab === 'resumen' ? <ResumenPanel /> : <DetallePanel />}`.
   Panels implemented in T-15 and T-16.

**Commit message**: `feat(dashboard-tplink): page scaffold, header with TP-Link logo, filter bar, tab shell`

**Manual verification**: navigate to `/dashboard-tplink` (once route added in T-17), confirm logo renders, filters visible, tabs switch.

---

#### [x] T-15 · IMPL · Resumen tab — KPIs + Categorías + Por Día chart + Logística + Top Productos

**Spec**: Frontend view §Resumen tab  
**Design**: §8, §6 ADR-4 (no Top Marcas block, no offset blocks)  
**File**: `frontend/src/pages/DashboardTPLink.jsx`  
**What**: Implement the Resumen tab content by calling and rendering:
1. `GET /api/dashboard-tplink/metricas-generales` → KPI cards:
   - Volume KPIs (always): `total_ventas_ml`, `cantidad_operaciones`, `cantidad_unidades`, `total_envios`, `total_limpio`
   - Margin KPIs (gated): `total_ganancia`, `markup_porcentaje`, `total_costo`, `total_comisiones`
     → render `puedeVerGanancia ? formatear(value) : '***'`
   - **NO offset KPI block** (do not port `DashboardMetricasML.jsx:976-991`)
2. `GET /api/dashboard-tplink/por-categoria` → Categorías breakdown table/chart.
3. `GET /api/dashboard-tplink/por-dia` → daily line chart.
4. `GET /api/dashboard-tplink/por-logistica` → logística breakdown card.
   - **NO offset line** (do not port `DashboardMetricasML.jsx:1128-1129`)
5. `GET /api/dashboard-tplink/top-productos` → Top Productos table.
   - **NO Top Marcas block** (removed per additional decided input; free the space for Categorías + Top Productos).
6. Margin fields render `***` when `puedeVerGanancia` is false. Because the server
   OMITS these keys, guard with optional chaining: `data?.total_ganancia ?? null`.
7. Use lucide-react icons throughout. CSS Modules for layout. Tesla design tokens.

**Commit message**: `feat(dashboard-tplink): Resumen tab — KPIs, categorías, por-día, logística, top-productos (no offsets, no top-marcas)`

**Manual verification**: log in as user with `.ver` only — confirm margin cells show `***`. Grant `.ver_ganancia` override — confirm real values appear. Confirm no offset cells present. Confirm no Top Marcas section.

---

#### [x] T-16 · IMPL · Detalle de Operaciones tab — paginated operations table

**Spec**: Frontend view §Detalle tab; API Surface §operaciones  
**Design**: §8  
**File**: `frontend/src/pages/DashboardTPLink.jsx`  
**What**: Implement the Detalle tab content:
1. Calls `GET /api/dashboard-tplink/operaciones` with current date + categoría filters.
2. Renders a table using `table-tesla.css` composition.
3. Non-margin columns always visible: `id_operacion`, `fecha_venta`, `descripcion`,
   `categoria`, `cantidad`, `monto_unitario`, `monto_total`, `costo_envio`,
   `monto_limpio`, `is_cancelled`.
4. Margin columns gated by `puedeVerGanancia`: `comision_porcentaje`, `comision_pesos`,
   `costo_sin_iva`, `costo_total`, `markup_porcentaje` → show `***` or hide column
   header when `!puedeVerGanancia`.
5. **NO `offset_flex` column** (do not port `DashboardMetricasML.jsx:842-843`).
6. Loading state with skeleton rows. Error state.

**Commit message**: `feat(dashboard-tplink): Detalle tab — operations table with margin gating, no offset column`

**Manual verification**: verify `offset_flex` column absent. Verify margin columns show `***` without `.ver_ganancia`.

---

### Phase 2-C — Routing + Sidebar (sequential, can parallel with 2-B)

#### [x] T-17 · IMPL · Route + ProtectedRoute in `App.jsx`

**Spec**: Frontend view §route  
**Design**: §8  
**File**: `frontend/src/App.jsx`  
**What**:
1. Add lazy/eager import: `import DashboardTPLink from './pages/DashboardTPLink'`
   (match existing pattern in `App.jsx`).
2. Add route: `<ProtectedRoute permiso="dashboard_tplink.ver"><DashboardTPLink /></ProtectedRoute>`
   at path `/dashboard-tplink`.
3. Review `SmartRedirect` (`App.jsx:119`): confirm a user whose ONLY permission is
   `dashboard_tplink.ver` lands on `/dashboard-tplink` as their home. If `SmartRedirect`
   routes by role only (no permission-aware branch), add a branch:
   ```js
   if (tienePermiso('dashboard_tplink.ver')) return <Navigate to="/dashboard-tplink" />
   ```
   Add this BEFORE the role-based fallback so it fires first.

**Commit message**: `feat(routing): add /dashboard-tplink ProtectedRoute and SmartRedirect branch for brand user`

**Manual verification**: visit `/dashboard-tplink` without permission → redirected. Log in as brand user → lands on `/dashboard-tplink`.

---

#### [x] T-18 · IMPL · Sidebar entry — gated by `dashboard_tplink.ver`

**Spec**: Frontend view §sidebar entry  
**Design**: §8  
**File**: `frontend/src/components/Sidebar.jsx` (or wherever nav entries live)  
**What**:
1. Add a sidebar nav entry for TP-Link Dashboard, visible only when
   `tienePermiso('dashboard_tplink.ver')`.
2. Use a lucide-react icon (e.g. `BarChart2` or `TrendingUp`).
3. Link to `/dashboard-tplink`.
4. A brand user (only `.ver` permission) should see ONLY this entry — the existing
   `tienePermiso` guards on other entries handle this automatically.

**Commit message**: `feat(sidebar): add TP-Link Dashboard nav entry gated by dashboard_tplink.ver`

**Manual verification**: log in as brand user → sidebar shows only the TP-Link entry. Internal admin → entry visible alongside all others.

---

#### [x] T-19 · VERIFY · Full manual QA pass (frontend)

**What**: Manual test run against the full frontend spec:
- [ ] `/dashboard-tplink` route loads without errors
- [ ] TP-Link logo (`/brand/tplink-logo-white.png`) visible in header
- [ ] Teal accent (`#4ACBD6`) applies via `--tplink-accent` token; other pages unaffected
- [ ] Dark mode: accent holds, surface tokens still flow from ThemeContext
- [ ] Categoría filter populates from `/api/dashboard-tplink/categorias-disponibles`
- [ ] Date filter changes trigger re-fetch on all panels
- [ ] Resumen tab: KPIs, categorías, por-día, logística, top-productos all load
- [ ] **No Top Marcas block** in Resumen tab
- [ ] **No offset KPI / offset row** anywhere on the page
- [ ] Margin fields show `***` without `.ver_ganancia`; real values with it
- [ ] Detalle tab: operations table loads; no `offset_flex` column
- [ ] 401 redirect when unauthenticated
- [ ] 403 handling when user lacks `.ver`
- [ ] Brand user SmartRedirect lands on `/dashboard-tplink`
- [ ] Sidebar shows only TP-Link entry for brand user

---

## Parallel / Sequential Map

```
T-01 (alembic head pre-check)
  └─► T-02 (migration write)
        └─► T-03 (migration test)
              └─► T-04 (RED gate tests)
                    └─► T-05 (router scaffold + register)     ← T-04 GREEN
                          └─► T-06 (RED store-lock tests)
                                └─► T-07 (implement 6 handlers)   ← T-06 GREEN
                                      ├─► T-08 (RED margin tests)
                                      ├─► T-09 (RED offset tests)
                                      └─► T-10 (RED superadmin test)
                                               └─► T-11 (full test run)
                                                     └─► T-12 (alembic round-trip)
─────────────────────────────────────────────────────────────────────
                   ┌──────────────────────────┐
                   │  PR #1 merged to main    │
                   └──────────────────────────┘
T-13 (CSS module + --tplink-accent)
  └─► T-14 (page scaffold)
        ├─► T-15 (Resumen tab)       ┐
        ├─► T-16 (Detalle tab)       ├─ parallel
        └─► T-17 + T-18 (route +    ┘   (all depend on T-14 scaffold)
             sidebar)
                    └─► T-19 (manual QA pass)
```

Phase 2-B and 2-C tasks (T-15, T-16, T-17, T-18) can be implemented in parallel once
T-14 exists. T-19 waits for all of Phase 2.

---

## Review Workload Forecast

| Area | File | Est. lines |
|------|------|-----------|
| Alembic migration | `20260624_add_permisos_dashboard_tplink.py` | ~80 |
| Migration test | `test_dashboard_tplink_permisos.py` | ~40 |
| Brand router (models + 6 handlers) | `dashboard_tplink.py` | ~300–380 |
| Helper extraction in `dashboard_ml.py` | modified | ~40 |
| `main.py` router registration | modified | ~2 |
| Integration tests | `test_dashboard_tplink.py` | ~280–340 |
| **PR #1 total** | | **~740–880 lines** |
| | | |
| CSS Module | `DashboardTPLink.module.css` | ~150–250 |
| Page component | `DashboardTPLink.jsx` | ~550–750 |
| `App.jsx` (route + SmartRedirect) | modified | ~15 |
| `Sidebar.jsx` (entry) | modified | ~10 |
| **PR #2 total** | | **~725–1025 lines** |
| | | |
| **Grand total** | | **~1465–1905 lines** |

**Chained PRs recommended: Yes**
**400-line budget risk: High** (both slices exceed 400 lines independently)
**Decision needed before apply: No** — chained strategy already resolved (stacked-to-main)

### PR budget note

Each slice independently exceeds 400 lines. This is unavoidable given the nature
of the work (a new router with 6 endpoints + full test coverage; a new ~600-line
page component). The test file alone in PR #1 is ~300 lines; removing tests would
violate the strict TDD contract. Both PRs are still well under the ~60-minute
review target if the reviewer focuses on the security boundary (PR #1) and the
UI surface (PR #2) independently. No further splitting is recommended — splitting
the router or the page further would produce non-deployable half-features.
