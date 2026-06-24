# Spec: Frontend View — dashboard-tplink-vista-marca

## Purpose

Define the structure, behavior, and access control of the new `DashboardTPLink`
page, its route, and its sidebar entry.

---

## Requirement: New Page `DashboardTPLink`

A new page component MUST be created at
`frontend/src/pages/DashboardTPLink.jsx` with a companion CSS module at
`frontend/src/pages/DashboardTPLink.module.css`.

The page is a restricted clone of `DashboardMetricasML.jsx` with the following
structural differences:

| Aspect | DashboardMetricasML | DashboardTPLink |
|--------|---------------------|-----------------|
| Tabs | Resumen, Detalle de Operaciones, Rentabilidad | Resumen + Detalle de Operaciones ONLY |
| Store selector | Present | Absent |
| PM selector | Present | Absent |
| Marca selector | Present | Absent |
| Filters available | Date range, categoría, marca, tienda, PM | Date range + categoría ONLY |
| Offset columns | Present in operaciones table | Absent |
| Header branding | Internal title/logo | TP-Link logo, accent color, page title "TP-Link Dashboard" |

---

## Requirement: Route

A new protected route MUST be added in `frontend/src/App.jsx`:

- Path: `/dashboard-tplink`
- Guard: `ProtectedRoute permiso="dashboard_tplink.ver"`
- Component: `DashboardTPLink`

A user who navigates to `/dashboard-tplink` without `dashboard_tplink.ver` MUST
be redirected (or shown a 403 page) by the `ProtectedRoute` component, consistent
with how other protected routes work in the app.

### Scenario: User without `.ver` cannot reach the page

- GIVEN user U does NOT have `dashboard_tplink.ver`
- WHEN user U navigates to `/dashboard-tplink`
- THEN the page is not rendered and U is redirected (same behavior as other
  `ProtectedRoute`-guarded pages when permission is missing)

---

## Requirement: Sidebar Entry

A new entry MUST be added to the `menuSections` array in `Sidebar.jsx` for the
TP-Link dashboard. The entry MUST be hidden when `tienePermiso("dashboard_tplink.ver")`
returns `false`.

- Label: `"TP-Link Dashboard"` (or equivalent brand-appropriate label)
- Path: `/dashboard-tplink`
- `permiso`: `"dashboard_tplink.ver"`
- Icon: an appropriate lucide-react icon (e.g., `BarChart2` or `Monitor`)

### Scenario: Sidebar entry hidden for users without `.ver`

- GIVEN user U does NOT have `dashboard_tplink.ver`
- WHEN the sidebar renders
- THEN no menu item pointing to `/dashboard-tplink` is visible

### Scenario: Sidebar entry visible for users with `.ver`

- GIVEN user U has `dashboard_tplink.ver`
- WHEN the sidebar renders
- THEN a menu item pointing to `/dashboard-tplink` is visible

---

## Requirement: Resumen Tab

The Resumen tab MUST display:

- **KPI metrics row**: `total_ventas_ml`, `total_limpio`, `cantidad_operaciones`,
  `cantidad_unidades`, `total_envios` — always visible.
- **Margin KPIs**: `total_ganancia`, `markup_porcentaje`, `total_costo`,
  `total_comisiones` — displayed as `***` when `tienePermiso("dashboard_tplink.ver_ganancia")`
  is `false`; real value when `true`.
- **Ventas por día chart**: `fecha` + `total_ventas` (always visible).
- **Ventas por categoría chart/table**: `categoria` + `total_ventas` (always visible).
- **Ventas por logística table**: `tipo_logistica`, `total_ventas`, `total_envios`,
  `cantidad_operaciones` — always visible, NO offset column.
- **Top productos table**: `codigo`, `descripcion`, `total_ventas`, `cantidad_unidades`
  always visible; `total_ganancia`, `markup_porcentaje` shown as `***` or real value
  depending on `.ver_ganancia`.

The Resumen tab MUST NOT contain:

- Any offset KPI, column, or row.
- Any store selector, PM selector, or marca selector filter control.
- A Rentabilidad section or link.

### Scenario: Margin KPIs masked when `.ver_ganancia` absent

- GIVEN user U has `dashboard_tplink.ver` only
- WHEN the Resumen tab is displayed
- THEN `total_ganancia`, `markup_porcentaje`, `total_costo`, `total_comisiones`
  are shown as `"***"` (or equivalent non-numeric placeholder)
- AND volume/facturación KPIs display their real numeric values

---

## Requirement: Detalle de Operaciones Tab

The operations table MUST display all columns from `OperacionTPLinkResponse`
except offset fields. Column visibility follows the margin gate:

| Column | Visible when | Masked when |
|--------|-------------|------------|
| `fecha_venta` | Always | — |
| `descripcion` | Always | — |
| `categoria` | Always | — |
| `monto_total` | Always | — |
| `cantidad` | Always | — |
| `monto_limpio` | Always | — |
| `costo_envio` | Always | — |
| `tipo_publicacion` | Always | — |
| `is_cancelled` | Always (row styling) | — |
| `comision_porcentaje` | `.ver_ganancia` present | `***` |
| `comision_pesos` | `.ver_ganancia` present | `***` |
| `costo_sin_iva` | `.ver_ganancia` present | `***` |
| `costo_total` | `.ver_ganancia` present | `***` |
| `markup_porcentaje` | `.ver_ganancia` present | `***` |

`offset_flex` column MUST NOT exist anywhere in the table — not as a hidden column,
not masked.

### Scenario: No offset column in operaciones table

- GIVEN any authenticated user with `dashboard_tplink.ver`
- WHEN the Detalle de Operaciones tab is displayed
- THEN no column header or cell related to `offset_flex` or offsets is present

---

## Requirement: Filters

The page MUST expose exactly two filter controls:

1. **Date range picker**: `fecha_desde` + `fecha_hasta` (YYYY-MM-DD).
2. **Categoría selector**: populated from `GET /dashboard-tplink/categorias-disponibles`.

The page MUST NOT expose any of:
- Store selector
- PM selector
- Marca selector
- Rentabilidad time-range or comparisons

---

## Requirement: TP-Link Branding

The page MUST apply TP-Link brand styling scoped to `DashboardTPLink.module.css`:

- A TP-Link logo in the page header.
- An accent color token override for the TP-Link red (`#e8000d` or the official
  brand hex, confirmed at design time).
- Page title: `"TP-Link — Dashboard de Ventas"` (or equivalent).
- All styling via CSS Modules + design token overrides. No Tailwind, no inline styles,
  no edits to `design-tokens.css` shared values.

The TP-Link theming MUST NOT affect any other page in the application.

---

## Out of Scope

- Rentabilidad tab — not included.
- Export button — not in v1.
- Mobile-specific layout beyond what the existing shared components already handle.
- Light/dark mode theming for the TP-Link accent color (follow-up if requested).
