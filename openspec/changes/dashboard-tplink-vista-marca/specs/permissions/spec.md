# Spec: Permission Model — dashboard-tplink-vista-marca

## Purpose

Define the two new granular permissions that gate the TP-Link brand dashboard,
their seeding in the database, and the exact behavioral contract for each
permission level.

---

## Requirement: Two New Permission Codes

The system MUST add two new entries to the `permisos` table:

| Code | Description |
|------|-------------|
| `dashboard_tplink.ver` | Grants page access and non-sensitive data (volume, facturación, units, ops, top products, ventas por día/categoría/logística) |
| `dashboard_tplink.ver_ganancia` | Unlocks the margin group (ganancia $, markup %, costos, comisiones) — requires `dashboard_tplink.ver` to also be present |

Both permissions MUST be seeded in the `permisos` table via an Alembic migration.
`dashboard_tplink.ver_ganancia` without `dashboard_tplink.ver` is meaningless (the
route itself is gated by `.ver`), but this is not enforced as a hard constraint —
the `.ver` gate handles the route.

### Scenario: Migration seeds both permissions

- GIVEN the Alembic migration `{date}_dashboard_tplink_permisos.py` is applied
- WHEN the `permisos` table is queried for `codigo LIKE 'dashboard_tplink.%'`
- THEN exactly two rows are returned: `dashboard_tplink.ver` and
  `dashboard_tplink.ver_ganancia`

---

## Requirement: Role Assignment

`dashboard_tplink.ver` and `dashboard_tplink.ver_ganancia` MUST be assigned to
the ADMIN and GERENTE roles via `rol_permiso_base` in the same migration, so
that internal users retain full visibility by default.

The brand-facing user (`usuario_id` TBD at provisioning time) MUST receive
`dashboard_tplink.ver` via a `usuario_permiso_override` row (`concedido=True`).
Granting `dashboard_tplink.ver_ganancia` to the brand user is optional and
decided at provisioning time. The migration does NOT pre-create the brand user
override; that is an operational step.

### Scenario: Internal admin sees the TP-Link page

- GIVEN user U has role ADMIN
- WHEN `PermisosService.tiene_permiso(U, "dashboard_tplink.ver")` is called
- THEN it returns `True` (via `rol_permiso_base` without any override)

### Scenario: Brand user gets access via override

- GIVEN user B has role that does NOT include `dashboard_tplink.ver` in `rol_permiso_base`
- AND a `usuario_permiso_override` row exists for B with `concedido=True` for `dashboard_tplink.ver`
- WHEN `PermisosService.tiene_permiso(B, "dashboard_tplink.ver")` is called
- THEN it returns `True`

### Scenario: SUPERADMIN always has access

- GIVEN user S has `es_superadmin = True`
- WHEN `PermisosService.tiene_permiso(S, "dashboard_tplink.ver")` is called
- AND `PermisosService.tiene_permiso(S, "dashboard_tplink.ver_ganancia")` is called
- THEN both return `True` regardless of any `permisos` or override rows

---

## Requirement: Route Access Gate (`.ver`)

Every `/dashboard-tplink/*` endpoint MUST require `dashboard_tplink.ver`. A
request that carries a valid JWT for a user who lacks this permission MUST receive
HTTP 403.

A request with no JWT MUST receive HTTP 401.

### Scenario: Unauthenticated request is rejected with 401

- GIVEN no Authorization header is present in the request
- WHEN `GET /dashboard-tplink/metricas-generales` is called
- THEN the response status is `401`

### Scenario: Authenticated user without `.ver` is rejected with 403

- GIVEN user U is authenticated (valid JWT)
- AND U does NOT have `dashboard_tplink.ver` (no role grant, no override, not superadmin)
- WHEN `GET /dashboard-tplink/metricas-generales` is called
- THEN the response status is `403`

### Scenario: Authenticated user with `.ver` receives data

- GIVEN user U is authenticated and has `dashboard_tplink.ver`
- WHEN `GET /dashboard-tplink/metricas-generales` is called with valid date params
- THEN the response status is `200`
- AND the body contains a valid `MetricasGeneralesTPLinkResponse` payload

---

## Requirement: Margin Gate (`.ver_ganancia`)

Margin fields (ganancia, markup_porcentaje, costo, comisiones) MUST be omitted or
neutralized in the server response when `dashboard_tplink.ver_ganancia` is absent.
The frontend `***` masking is a display layer only; the authoritative boundary is
the server.

**Margin fields** (exhaustive list):
- `total_ganancia`
- `markup_porcentaje`
- `total_costo`
- `total_comisiones`

**Non-margin fields** (never masked):
- `total_ventas_ml`
- `total_limpio`
- `cantidad_operaciones`
- `cantidad_unidades`
- `total_envios`
- Any date, categoría, or product-description field

### Scenario: User with `.ver` only — margin fields are neutralized server-side

- GIVEN user U has `dashboard_tplink.ver` but NOT `dashboard_tplink.ver_ganancia`
- WHEN `GET /dashboard-tplink/metricas-generales` is called
- THEN the response status is `200`
- AND `total_ganancia` is `null` or `0` (not the real value)
- AND `markup_porcentaje` is `null` or `0`
- AND `total_costo` is `null` or `0`
- AND `total_comisiones` is `null` or `0`
- AND `total_ventas_ml`, `cantidad_operaciones`, `cantidad_unidades`, `total_envios`
  contain real values

### Scenario: User with both permissions — margin fields contain real values

- GIVEN user U has `dashboard_tplink.ver` AND `dashboard_tplink.ver_ganancia`
- WHEN `GET /dashboard-tplink/metricas-generales` is called with data in range
- THEN `total_ganancia` is the real computed value (non-zero when sales exist)
- AND `markup_porcentaje` reflects the real markup

### Scenario: Margin masking applies to per-row endpoints too

- GIVEN user U has `dashboard_tplink.ver` but NOT `dashboard_tplink.ver_ganancia`
- WHEN `GET /dashboard-tplink/operaciones` is called
- THEN in every row of the response: `markup_porcentaje`, `comision_pesos`,
  `costo_sin_iva`, `costo_total` are `null` or `0`

---

## Out of Scope

- Fixing the pre-existing permission gap on `/dashboard-ml/*` endpoints (auth-only,
  no permission gate) — separate audit item.
- Self-service brand user provisioning UI.
- Revoking `dashboard_tplink.ver_ganancia` at runtime without re-login
  (permission cache is per-request in the current implementation).
