# Spec: Brand API Surface — dashboard-tplink-vista-marca

## Purpose

Define the full set of `/dashboard-tplink/*` endpoints, their request parameters,
response shapes, and which fields are subject to margin gating.

---

## Requirement: Dedicated Brand Router at `/dashboard-tplink`

A new FastAPI router MUST be created at
`backend/app/api/endpoints/dashboard_tplink.py` and registered in `main.py` with
prefix `/api`. All endpoints use the `GET` method. All endpoints require valid JWT
authentication and `dashboard_tplink.ver` permission (checked in every handler via
`PermisosService.tiene_permiso`).

### Accepted query parameters (all endpoints)

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `fecha_desde` | `str` (YYYY-MM-DD) | No | Inclusive lower bound, Argentina TZ |
| `fecha_hasta` | `str` (YYYY-MM-DD) | No | Inclusive upper bound, Argentina TZ |
| `categorias` | `str` (comma-separated) | No | Filter by one or more categories |

No other parameters are accepted. `tiendas_oficiales`, `pm_ids`, `marcas` are
intentionally absent from all endpoint signatures.

---

## Requirement: `GET /dashboard-tplink/metricas-generales`

Mirrors `GET /dashboard-ml/metricas-generales` minus `total_offset_flex`.

### Response model: `MetricasGeneralesTPLinkResponse`

| Field | Type | Margin-gated |
|-------|------|-------------|
| `total_ventas_ml` | `Decimal` | No |
| `total_limpio` | `Decimal` | No |
| `cantidad_operaciones` | `int` | No |
| `cantidad_unidades` | `int` | No |
| `total_envios` | `Decimal` | No |
| `total_ganancia` | `Decimal \| None` | Yes — `null` when `.ver_ganancia` absent |
| `markup_porcentaje` | `Decimal \| None` | Yes — `null` when `.ver_ganancia` absent |
| `total_costo` | `Decimal \| None` | Yes — `null` when `.ver_ganancia` absent |
| `total_comisiones` | `Decimal \| None` | Yes — `null` when `.ver_ganancia` absent |

`total_offset_flex` MUST NOT appear in this response.

### Scenario: Margin fields null when `.ver_ganancia` absent

- GIVEN user U has `dashboard_tplink.ver` only
- WHEN `GET /dashboard-tplink/metricas-generales` returns a result
- THEN `total_ganancia`, `markup_porcentaje`, `total_costo`, `total_comisiones` are `null`
- AND `total_ventas_ml`, `cantidad_operaciones`, `cantidad_unidades`, `total_envios` are real values

### Scenario: No offset field in response ever

- GIVEN any authenticated user with `dashboard_tplink.ver`
- WHEN `GET /dashboard-tplink/metricas-generales` is called
- THEN the JSON response DOES NOT contain a key named `total_offset_flex`
  or any other `offset` key

---

## Requirement: `GET /dashboard-tplink/por-categoria`

Mirrors `GET /dashboard-ml/por-categoria` minus margin-gated fields when
`.ver_ganancia` is absent. Accepts `fecha_desde`, `fecha_hasta`, `categorias`.

### Response model: `VentaPorCategoriaTPLinkResponse` (list)

| Field | Type | Margin-gated |
|-------|------|-------------|
| `categoria` | `str` | No |
| `total_ventas` | `Decimal` | No |
| `total_limpio` | `Decimal` | No |
| `cantidad_operaciones` | `int` | No |
| `total_ganancia` | `Decimal \| None` | Yes |
| `markup_porcentaje` | `Decimal \| None` | Yes |

---

## Requirement: `GET /dashboard-tplink/por-logistica`

Mirrors `GET /dashboard-ml/por-logistica` minus any offset field.

### Response model: `VentaPorLogisticaTPLinkResponse` (list)

| Field | Type | Margin-gated |
|-------|------|-------------|
| `tipo_logistica` | `str` | No |
| `total_ventas` | `Decimal` | No |
| `total_envios` | `Decimal` | No |
| `cantidad_operaciones` | `int` | No |

`total_offset_flex` MUST NOT appear in this response.

---

## Requirement: `GET /dashboard-tplink/por-dia`

Mirrors `GET /dashboard-ml/por-dia` minus margin-gated fields when `.ver_ganancia`
is absent.

### Response model: `VentaDiariaTPLinkResponse` (list)

| Field | Type | Margin-gated |
|-------|------|-------------|
| `fecha` | `date` | No |
| `total_ventas` | `Decimal` | No |
| `total_limpio` | `Decimal` | No |
| `cantidad_operaciones` | `int` | No |
| `total_ganancia` | `Decimal \| None` | Yes |

---

## Requirement: `GET /dashboard-tplink/top-productos`

Mirrors `GET /dashboard-ml/top-productos` minus margin-gated fields when
`.ver_ganancia` is absent.

### Response model: `TopProductoTPLinkResponse` (list)

| Field | Type | Margin-gated |
|-------|------|-------------|
| `item_id` | `int` | No |
| `codigo` | `str \| None` | No |
| `descripcion` | `str \| None` | No |
| `marca` | `str \| None` | No |
| `total_ventas` | `Decimal` | No |
| `cantidad_operaciones` | `int` | No |
| `cantidad_unidades` | `int` | No |
| `total_ganancia` | `Decimal \| None` | Yes |
| `markup_porcentaje` | `Decimal \| None` | Yes |

---

## Requirement: `GET /dashboard-tplink/operaciones`

Backs the Detalle de Operaciones tab. Mirrors
`GET /ventas-ml/operaciones-con-metricas` with the following differences:

- Store 2645 forced (not a param).
- `offset_flex` field MUST be absent from the response.
- Margin fields gated by `dashboard_tplink.ver_ganancia`.
- Date params are named `fecha_desde` / `fecha_hasta` (YYYY-MM-DD), consistent
  with the rest of the brand router (not `from_date` / `to_date`).

### Response model: `OperacionTPLinkResponse` (list)

| Field | Type | Margin-gated |
|-------|------|-------------|
| `id_operacion` | `int` | No |
| `ml_id` | `str \| None` | No |
| `pack_id` | `int \| None` | No |
| `fecha_venta` | `datetime` | No |
| `item_id` | `int \| None` | No |
| `codigo` | `str \| None` | No |
| `descripcion` | `str \| None` | No |
| `categoria` | `str \| None` | No |
| `subcategoria` | `str \| None` | No |
| `marca` | `str \| None` | No |
| `cantidad` | `Decimal` | No |
| `monto_unitario` | `Decimal` | No |
| `monto_total` | `Decimal` | No |
| `iva` | `Decimal` | No |
| `tipo_publicacion` | `str \| None` | No |
| `costo_envio` | `Decimal` | No |
| `monto_limpio` | `Decimal` | No |
| `is_cancelled` | `bool` | No |
| `comision_porcentaje` | `Decimal \| None` | Yes |
| `comision_pesos` | `Decimal \| None` | Yes |
| `costo_sin_iva` | `Decimal \| None` | Yes |
| `costo_total` | `Decimal \| None` | Yes |
| `markup_porcentaje` | `Decimal \| None` | Yes |

`offset_flex` MUST NOT appear in this response.

### Scenario: offset_flex absent from operaciones response

- GIVEN any authenticated user with `dashboard_tplink.ver`
- WHEN `GET /dashboard-tplink/operaciones` is called
- THEN no row in the response array contains an `offset_flex` key

---

## Requirement: `GET /dashboard-tplink/categorias-disponibles`

Returns the list of distinct `categoria` values present in `MLVentaMetrica` for
store 2645, to populate the categoría filter dropdown. No margin gating needed.

### Response

`List[str]` — list of category name strings, sorted alphabetically.

---

## Requirement: No Offset Field in Any Response

No `/dashboard-tplink/*` endpoint response MUST contain any field named
`offset_flex`, `total_offset_flex`, `rendimientos_offset`, or any variation
thereof. This is unconditional — no permission unlocks offsets.

### Scenario: Exhaustive offset absence

- GIVEN any valid request to any `/dashboard-tplink/*` endpoint
- WHEN the response JSON is inspected recursively
- THEN no key matching `*offset*` exists at any level of nesting

---

## Out of Scope

- `GET /dashboard-tplink/por-marca` — the brand view is already scoped to TP-Link
  so a per-marca breakdown is not meaningful; not included.
- Export (Excel/CSV) endpoint — not in v1.
- Pagination — all endpoints return full result sets as the existing ML endpoints do.
- `/dashboard-tplink/mis-marcas` equivalent — the store lock makes this redundant.
