# Admin permisos por pantalla

Locator: `odd/tasks/admin-permisos-por-pantalla.md` · Engram topic `odd/admin-permisos-por-pantalla/tasks`
Branch: `feat/admin-permisos-por-pantalla` (off origin/main 5a341031)
Design: Stitch project `projects/3291827526597537807` (screens "Permisos por Usuario" 789bdb8b…, "Roles y Permisos (Matriz)" 4e464fb2…), approved by owner 2026-10-09 ("muchísimo mejor que lo actual").

## Objective
Rebuild the two Admin permission tabs (`PanelPermisos.jsx` users, `PanelRoles.jsx` roles) so they are practical: see what a user is missing, find the permission a screen needs, and review everything without scrolling a flat list.

## Problem / why
- Permissions are a flat per-category list; no link to the screens they unlock.
- Screen→permission mapping is duplicated by hand in `App.jsx` (`protectedRoutes`) and `Sidebar.jsx` (`menuSections`).
- `CATEGORIAS_NOMBRE` is copied in both panels and covers 8 of ~16 categories.
- Data-scoped screens (Métricas ML etc. via `pm_scope.py`) can look broken with the right permission when a sub-PM has no delegated marca/categoría pairs; the UI cannot explain it.

## Scope
- Shared screen catalog + access helpers (pure, tested).
- Usuarios tab: split layout, KPIs, search, "Por pantalla | Por permiso", filter chips, expandable screen rows with origin (rol / +override / −override / falta), inline Conceder/Quitar/Resetear, CONDICIONAL rows for data-scoped screens.
- Roles tab: roles × permissions matrix grouped by screen, pending-change state, sticky save bar, role drawer.
- Novedad entry in `frontend/src/novedades`.

## Constraints
- Do not touch Publicaciones ML files (`frontend/src/components/publicacionesMl/`, `pages/PublicacionesML*`), and do not move the `/ml-publicaciones` route line in `App.jsx` (test regex-matches it).
- No App.jsx/Sidebar.jsx refactor in this feature: catalog is a new module guarded by a drift test against `App.jsx` source.
- Design tokens + CSS Modules only (no Tailwind, no hardcoded colors); kit components where they fit.
- Strict TDD: RED before GREEN. No AI attribution in commits/PRs. Fix all GGA observations before delivery.
- No backend changes unless strictly required (existing endpoints cover it).

## Tasks
Re-sliced so no PR ships an unused registry (forward-dependency rule): the catalog lands together with its first consumer.

- [ ] T1 (PR1) Screen catalog + access helpers in `frontend/src/registry/` (screens `{path,label,section,permisos[],scope}`, full category labels, `accesoPantalla` → accede/parcial/sin_acceso/condicional + origin, drift test vs `App.jsx` protectedRoutes) AND new `PermisosPorPantalla` component replacing the permissions block inside the current `PanelPermisos.jsx` (search, filter chips, expandable rows, Conceder/Quitar/Resetear, CONDICIONAL via `GET /marcas-pm/sub-pms/conteos`) + novedad. Route: delegated writer (2+ non-trivial files).
- [ ] T2 (PR2) Usuarios tab shell: split layout, user list with role/override chips, KPI strip, user create/edit moved to a modal, "Por pantalla | Por permiso" segmented control. Route: delegated writer.
- [ ] T3 (PR3) Roles tab matrix (`PanelRoles.jsx` + subcomponents): loads `/roles/{id}/permisos` per role, pending-change state, sticky save bar, PUT only dirty roles, role drawer; novedad updated. Route: delegated writer.
- [ ] T4 (PR4, owner-approved 2026-10-09) Additional roles per user, permissions-only: new table `usuarios_roles_adicionales` (Alembic migration), `PermisosService.obtener_permisos_usuario` unions the primary role + additional roles' permissions, then applies overrides. `rol_id` stays the PRIMARY role and keeps deciding identity rules (superadmin, `pm_scope` full view `rol_codigo in FULL_VIEW_CODIGOS`, UI role labels) — an additional role never grants superadmin nor full brand view. Origin in `permisos_detallados` gains "rol adicional <codigo>"; Usuarios tab lets admins assign additional roles; Roles matrix counts users by primary + additional. Separate PR (model change + migration). Route: delegated writer.

## Acceptance criteria
- Per user: every catalog screen shows access status, required permissions and origin; filters Sin acceso / Con overrides / Críticos / Depende de datos work; Conceder/Quitar/Resetear call existing override endpoints and refresh.
- Per role: matrix shows all roles; toggling marks pending; save only PUTs changed roles; discard restores.
- Drift test fails if a protected route is added to App.jsx without a catalog entry.
- `pnpm test` for touched files green; `pnpm lint`/build green.

## Checks
- `cd frontend && pnpm test <files>`; `pnpm lint`; `pnpm build`.

## Delivery
- Forecast: PR1 ~2000 (T1 actual, incl. ~580 test + 378 CSS), PR2 ~700, PR3 ~650, PR4 ~500 authored lines → over 400; strategy `ask-on-risk`, chain = `stacked-to-main` (owner 2026-10-09). One PR per task against main; the next branch starts from main after the previous one merges. Novedad ships with PR1 (first visible change) and is updated in PR2/PR3.

## Progress
- 2026-10-09: design approved; branch created; exploration done.
- 2026-10-09 T1 (delegated writer, uncommitted, awaiting parent verification):
  - Added `frontend/src/registry/screenCatalog.js` (58 screens mirroring Sidebar sections + `Otras`; `CATEGORIAS_PERMISO` for 22 backend categories + `nombreCategoria` humanizer), `permisosAcceso.js` (status accede/sin_acceso/condicional/publica, origin, filters, accent-free search, grouping, permisos sin pantalla, `esFullView` mirroring pm_scope, `contarParesEfectivos`), `components/permisos/PermisosPorPantalla.jsx` + `.module.css`, novedad `2026-10-09-permisos-por-pantalla.md`.
  - `PanelPermisos.jsx`: old search+legend+category block replaced by `PermisosPorPantalla`; override calls moved into the component (same endpoints/payload/motivo); reload after an override is now in place (`recargarPermisosUsuario`, guarded by a selected-user ref) so search/filter/expanded rows survive. User list and user edit untouched. `PanelPermisos.module.css` left as is (shared with `PanelRoles.jsx`; some classes now unused).
  - Decisions: `scope: 'data'` = `/metricas-ml`, `/dashboard-metricas-ml`, `/consultas/ranking` (ranking bypass is `consultas.ver_ranking` only, per `consultas.py _scope_user_id`, modeled as `fullViewPermisos`). `/test-stats-dinamicos` excluded (dev test page; `EXCLUDED_ROUTES`, drift test keeps it honest). `/ml-publicaciones` listed under Otras as "Publicaciones ML (oculta)". CONDICIONAL pair count = titular pairs (`GET /marcas-pm`) + sub-PM grants (`GET /marcas-pm/sub-pms/conteos`), matching pm_scope's UNION; any failure -> unknown -> never CONDICIONAL. Actions gated by `tienePermiso('admin.gestionar_permisos')` (the backend gate of the override endpoints) and hidden for SUPERADMIN targets.
  - RED observed: permisosAcceso (module missing; later 3 failing `contarParesEfectivos is not a function`), screenCatalog drift (module missing), PermisosPorPantalla (module missing). PanelPermisos.test written after the wiring; RED shown by mutation (reload via `seleccionarUsuario` -> search value lost, test fails).
  - Checks: `pnpm test src/registry src/components/permisos src/components/PanelPermisos src/pages/Novedades src/App.publicacionesMlRoute` -> 6 files, 54 tests passed; `pnpm lint` -> 0 errors (2 pre-existing warnings in AppLayout.jsx); `pnpm build` -> success. Not done: manual visual check in light/dark.
