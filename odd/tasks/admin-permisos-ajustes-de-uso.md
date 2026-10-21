# Admin permissions: usability fixes after the redesign

## Objective

Fix four problems the owner found using the redesigned Admin permission tabs (feature `admin-permisos-por-pantalla`, closed 2026-10-15).

## Problem (owner, 2026-10-21, verbatim)

> "hay muchas cosas mal, primero Permisos sin pantalla: mezcla todos los permisos, si un permiso dice productos. claramente va dentro de productos sino cuando habilitás que vean una vista no habilitás los permisos adicionales porque no los ves, así con todos, por otro lado, en celular se ve todo para abajo es imposible de usar la vista nueva, la matriz de roles debería ocupar toda la pantalla seguro que tengas que hacerlo para todo el panel de admin, no hay problema, a seleccionar un rol no me destaca de ninguna manera sus permisos habilitados tengo que ver la matriz igual para todos, es al pedo seleccionarlo si no es para clonar."

> "tenés playwrith como mcp para ir viendo lo que generás" — verify every visible change with Playwright screenshots (desktop and phone width).

## Why

- About 130 of 150 permissions land in one "Permisos sin pantalla" bucket. Granting a screen hides its extra permissions (`productos.editar_precios` and the like), so admins grant the screen and miss what it needs.
- On a phone the Usuarios and Roles tabs stack everything vertically and the matrix scrolls the permission names out of view.
- `Admin.module.css:2` caps every tab at 1200px; the matrix needs the full width.
- Selecting a role only opens the drawer; the matrix does not show which column or which enabled permissions belong to it.

## Scope

- Frontend only: `frontend/src/registry/`, `frontend/src/components/permisos/`, `PanelPermisos*`, `PanelRoles*`, `frontend/src/components/roles/`, `frontend/src/pages/Admin*`, novedad.
- Do not touch `frontend/src/components/publicacionesMl/` or `pages/PublicacionesML*`.

## Tasks

- [x] T1 (PR1 #1667, merged 2026-10-21T13:41:46Z, commits a5fc94667 2fcd99477 verified ancestors of origin/main; branch `fix/admin-permisos-adicionales-por-pantalla` off origin/main de1d5932b) Show each extra permission under its screen in "Por pantalla": a permission whose codigo prefix (text before the first `.`) matches a screen's permissions goes under that screen as "Permisos adicionales" (they do not decide access). Explicit per-code/per-prefix overrides in the catalog for ambiguous prefixes (rma, ml_ops, produccion, reportes, administracion, admin). Only codes with no screen at all stay in a final "Otros permisos" group. Search, filters and chip counts include the extras. Novedad. Route: delegated writer (2+ non-trivial files).
- [ ] T2 (PR2) Roles tab: selecting a role highlights its column and its enabled cells in the matrix, plus a "Solo los permisos de este rol" toggle that filters rows to that role's enabled permissions. Novedad. Route: delegated writer.
- [ ] T3 (PR3) Layout: Admin page uses the full width (drop the 1200px cap), tabs scroll horizontally on a phone, reduced paddings on small screens; matrix keeps the permission column sticky on the left with short role headers; Usuarios tab on a phone shows list or detail (not both stacked); role drawer as an overlay on small screens. Verified with Playwright screenshots at 1440px and 390px. Novedad. Route: delegated writer.

## Delivery

Strategy `ask-on-risk`, chain `stacked-to-main` (owner's standing rule): each PR starts from fresh origin/main after the previous one merges. Forecast ~250-400 authored lines per PR.

## Acceptance criteria

- T1: with `productos.ver` granted, the Productos screen row lists `productos.editar_precios` etc. with their own Conceder/Quitar; no `productos.*` code appears in "Otros permisos".
- T2: clicking a role card visibly marks its column; the toggle leaves only rows where that role has the permission.
- T3: at 390px the Admin tabs, Usuarios and Roles are usable without horizontal page scroll; at 1440px the matrix spans the page.

## Checks

Vitest for the touched components + css-guard, eslint, stylelint, `pnpm build`, Novedades tests; Playwright screenshots for T1 and T3.

## Progress

- 2026-10-21 Exploration (read-only explorer): loose list built by `permisosSinPantalla` (`permisosAcceso.js:235`), rendered at `PermisosPorPantalla.jsx:180-192`; prefixes match screens better than backend `categoria`; width cap `Admin.module.css:2`; `rolAbiertoId` never reaches `MatrizRoles` (`PanelRoles.jsx:447-456`).
- 2026-10-21 T1 (route: delegated writer; trigger: 2+ non-trivial files). Pending parent check-off.
  - RED observed first: `pnpm exec vitest run src/registry src/components/permisos` -> 19 failed / 90 passed (109). Messages: `otrosPermisos is not a function`, `pantallasDeAdicional is not a function`, `Cannot read properties of undefined (reading 'prefijos')` (no `PERMISOS_ADICIONALES`), `Unable to find ... region "Otros permisos"`, `Unable to find an element with the text: +1 adicional`.
  - GREEN: same run 109/109; verification scope (registry + permisos + PanelPermisos + novedades) 160/160; eslint and stylelint clean; `pnpm build` OK.
  - Design: `PERMISOS_ADICIONALES = { prefijos, porPantalla }` in `screenCatalog.js`; resolution porPantalla (codigo) > prefijos > screens whose access codes share the prefix; access codes are never extras; `prefijos: []` sends a prefix to "Otros". Guard tests: map paths exist, no access code listed, every prefix opening 2+ screens has a `prefijos` entry. Filters: `sin_acceso` stays the screen status; `con_overrides` and `criticos` include extras; chip counts = screens (once) + "Otros" rows.
  - Overrides (prefix/codigo -> screen):

    | Prefix / codigo | Screen(s) |
    | --- | --- |
    | `productos` | /productos |
    | `productos.calcular_web_masivo`, `.editar_precio_cuotas`, `.marcar_color`, `.marcar_color_lote` | /productos, /tienda |
    | `productos.gestionar_markups_tienda`, `tienda` | /tienda |
    | `admin`, `config` | /admin |
    | `admin.gestionar_banlist` | /mla-banlist |
    | `admin.*` ItemsSinMLA + TN reconcile codes (10) | /items-sin-mla |
    | `administracion` | /administracion/compras |
    | `administracion.consultar_afip` | /administracion/proveedores |
    | `administracion.gestionar_proveedores` | /administracion/proveedores, /administracion/impuestos |
    | `administracion.gestionar_caja` | /administracion/caja, /administracion/bancos |
    | `administracion.sincronizar_caja` | /administracion/caja |
    | `rma` | /rma |
    | `rma.gestionar` | /rma, /claims |
    | `rma.control_deposito_no_baja` | /control-deposito |
    | `ml_ops` | /ml-publicaciones |
    | `ml_metricas.ver_ganancia` | /metricas-ml, /ml-publicaciones |
    | `ventas_ml.ver_todas_marcas` | /metricas-ml, /dashboard-metricas-ml |
    | `tplink.solo` | /metricas-ml |
    | `produccion` | /produccion |
    | `produccion.ver_preparacion`, `ordenes`, `envios_flex`, `pedidos` | /pedidos-preparacion |
    | `seguimiento_envios.flag` | /seguimiento-envios, /pedidos-preparacion |
    | `documentos.imprimir` | /pedidos-preparacion, /rma, /rrhh/empleados, /rrhh/presentismo |
    | `rrhh` | /rrhh/empleados |
    | `rrhh.config` | empleados, sanciones, horarios |
    | `rrhh.gestionar` | empleados, presentismo, sanciones, vacaciones, cuenta-corriente, horarios |
    | `rrhh.*horas_extras` (3) | /rrhh/horas-extras |
    | `reportes` | none (Otros) |
    | `reportes.recibir_notificaciones_markup` | /notificaciones |
    | `tickets` | /tickets |
    | `alertas` | /gestion/alertas |
    | `promos` | /productos, /ml-publicaciones |
    | `pxq`, `equipos` | /productos |
    | `sell_out` | /sell-in |
    | `tplink` | none (Otros) |
    | `deposito`, `tesoreria` | prefix default (/administracion/compras) |

  - Leftovers in "Otros" (from the ~192 codes extracted from alembic + catalog): `reportes.exportar`, `reportes.ver_auditoria`, `tplink.tema` (no frontend check, or a global theme flag).
- 2026-10-21 T1 review follow-up (2 R3 suggestions on a5fc94667): added tests for Quitar/Resetear on an extra row, an extra on two screens (rma.gestionar on /rma and /claims) and the pinned "Otros" set (exactly reportes.exportar, reportes.ver_auditoria, tplink.tema); all passed on the first run (coverage, not RED), `vitest run src/registry src/components/permisos` 113/113, eslint clean.
- 2026-10-21 T2 (route: delegated writer; trigger: 2+ non-trivial files; branch `feat/admin-roles-resaltar-seleccionado` off origin/main 851e06baf). Pending parent check-off and Playwright screenshots.
  - RED observed first: 7 new tests in `PanelRoles.test.jsx` ("PanelRoles selected role in the matrix"); `pnpm exec vitest run src/components/PanelRoles.test.jsx` -> 5 failed / 52 passed (57). Messages: `Unable to find an accessible element with the role "columnheader" and name "Ventas (seleccionado)"`, `expect(received).not.toBeChecked()` / `toBeChecked()` with `Received: null` (toggle missing), `Unable to find ... role "button" and name "Ver solo los 2 permisos de Administrador en la matriz"`. The 2 guard tests ("leaves the other columns unmarked", "hides the role filter toggle while no role is selected") passed in RED by construction.
  - GREEN: same file 57/57; verification scope (PanelRoles + roles + novedades) 70/70; css-guard 8/8; eslint and stylelint clean; `pnpm build` OK.
  - Design: `MatrizRoles` takes `rolSeleccionado` (the role open in the drawer), `soloDelRol`, `onSoloDelRolChange`. Selected header: `th.colRolSeleccionado` with `aria-current="true"` and a visually hidden "(seleccionado)" (name "Ventas (seleccionado)"); its cells get `celdaSeleccionada` (info tint + accent side borders), granted ones also `celdaConcedida` (stronger tint), unchecked boxes fade; pending warning tint still wins. Tokens only (`--tone-info-*`, `--cf-accent-blue`); the sticky header layers the translucent dark tint over `--cf-bg-card`.
  - Toggle "Solo los permisos de este rol (N)": shown only while a loaded role is selected (hidden for a role whose permissions failed to load); filters with the same `tienePermiso` as the cells (pending changes count); empty categories hidden; combines with the search. Behavior choice: it STAYS ON when switching to another role (applies to the new one, count updates) and turns OFF when the selection clears (close drawer, + Nuevo Rol, deleting the open role). State lives in `PanelRoles` so `DetalleRol` can turn it on: its loaded "Permisos" count is a link-like button (not for SUPERADMIN "Todos" or "Sin cargar").
  - Closing the drawer already cleared `rolAbiertoId`; the highlight follows it with no extra code.
  - 2026-10-21 T2 follow-up (parent Playwright check at 1440px): RED `vitest run src/components/PanelRoles.test.jsx` 3 failed / 58 passed (61) (`Unable to find ... role "table"` once the role's only row was unchecked under the filter; `expected "vi.fn()" to be called 1 times, but got 0 times`; `expected "vi.fn()" to be called with ... {"left": 120}`; "does not scroll when already visible" passed by construction) -> GREEN 61/61, scope + css-guard 82/82, eslint/stylelint clean, build OK. Selecting or switching roles calls `scrollTo({ left })` on the `.scroll` container only (never `scrollIntoView`, so the page never scrolls vertically), clear of the sticky "Permiso" column; with the filter on, a row stays while the selected role has a pending change on it (the count still counts only granted); "Permiso" header, names and category labels are sticky-left with opaque `--cf-bg-card`/`--cf-bg-hover` and the corner at `--z-sticky + 1` (CSS-only, no RED possible).
  - 2026-10-21 T2 follow-up 2 (parent Playwright: "ENTAS" clipped under "Permiso", blue dashes on the sticky edge): scroll target now from live `getBoundingClientRect()` (sticky header right edge to scroller left + clientWidth) instead of `offsetLeft`/`offsetWidth`; test layout faked via rects with the same exact `left` (420, 120). RED 2 failed / 59 passed (61) (`expected "vi.fn()" to be called 1 times, but got 0 times`; `... called with {"left": 120}`) -> GREEN 61/61, scope + css-guard 82/82, eslint/stylelint clean, build OK. CSS (no RED possible): table `border-collapse: separate; border-spacing: 0` so each cell paints its own borders and the sticky cells cover what scrolls under them; selected header and column marked with inset box-shadows instead of borders (pending + selected combines both).
  - 2026-10-21 T2 review follow-up (native review of d3f32df1, 3 R3 findings): 3 new tests (delete of the open role with a switch tried mid-DELETE, reopen after + Nuevo Rol, unloaded role) all PASSED on the first run = coverage, not RED. Their teeth were checked by mutation: removing the delete and + Nuevo Rol resets -> 2 failed / 62 passed (64), then the code was restored. Why the race was not reproducible: while the DELETE is in flight the role cards are disabled (`cambioDeRolBloqueado`), so the deleted role is always still the open one. Fix anyway: the three handler resets were replaced by one render-time derivation, `if (soloDelRol && rolAbiertoId === null) setSoloDelRol(false)`, which reads the current value rather than one a handler captured. Unloaded-role rule (asserted, the code already matched it): no toggle and no filtering for a role whose permissions failed to load, and the flag is kept so a loaded role shown afterwards is still filtered. GREEN: scope + css-guard 85/85, eslint/stylelint clean, build OK.
  - 2026-10-21 T2 second review (3accea68, R3-001): RED `vitest run src/components/PanelRoles.test.jsx` 1 failed / 64 passed (65) (`expected "vi.fn()" to be called 1 times, but got 0 times` when the table came back after a no-match search) -> the scroll effect now also depends on `hayFilas` (table mounted), GREEN 65/65, scope + css-guard 86/86, eslint/stylelint clean, build OK. Review loop closed after 2 passes.
