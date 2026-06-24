# Spec: Server-Side Store Lock — dashboard-tplink-vista-marca

## Purpose

Define the security contract that confines all `/dashboard-tplink/*` data to
TP-Link's official store (`mlp_official_store_id = 2645`), server-side, regardless
of any client-supplied query parameter.

---

## Requirement: Store 2645 Forced Server-Side

Every `/dashboard-tplink/*` endpoint MUST apply the store filter
`mlp_official_store_id = 2645` unconditionally, using the same subquery mechanism
as `aplicar_filtro_tienda_oficial` in `dashboard_ml.py`.

The endpoints MUST NOT accept any `tiendas_oficiales`, `pm_ids`, or `marcas`
query parameters. If such parameters are present in the request, they MUST be
ignored — the store scope remains 2645 regardless. The endpoint signature MUST NOT
declare these parameters.

### Scenario: Response is scoped to store 2645 regardless of absence of filter param

- GIVEN user U has `dashboard_tplink.ver`
- WHEN `GET /dashboard-tplink/metricas-generales` is called with no store param
- THEN the aggregated metrics reflect only rows where
  `MLVentaMetrica.mla_id` is in the set of `mlp_id` values linked to
  `MercadoLibreItemPublicado.mlp_official_store_id = 2645`

### Scenario: Query-string tampering with another store id has no effect

- GIVEN user U has `dashboard_tplink.ver`
- AND the request URL includes `?tiendas_oficiales=57997` (Gauss store)
- WHEN `GET /dashboard-tplink/metricas-generales` is called
- THEN the response is identical to the same request without that param
- AND no data from store 57997 appears in the response

### Scenario: Query-string with store 2645 explicitly has no effect

- GIVEN user U has `dashboard_tplink.ver`
- AND the request URL includes `?tiendas_oficiales=2645`
- WHEN `GET /dashboard-tplink/metricas-generales` is called
- THEN the response is `200` and contains the same data as the no-param request
  (the param is silently ignored, not an error)

---

## Requirement: No PM or Marca Scope Parameters

The brand router MUST NOT expose `pm_ids` or `marcas` parameters. The brand view
covers TP-Link products only; PM assignment logic (`aplicar_filtro_marcas_pm`) is
not applied because the store lock is sufficient to confine the scope.

### Scenario: pm_ids param in request is silently ignored

- GIVEN user U has `dashboard_tplink.ver`
- AND the request includes `?pm_ids=42`
- WHEN any `/dashboard-tplink/*` endpoint is called
- THEN the `pm_ids` param is not processed and does not alter the result

---

## Requirement: Isolation from Shared Endpoints

The `/dashboard-tplink/*` router MUST be a separate module from `dashboard_ml.py`.
Changes to `dashboard_ml.py` (parameters, filters, helper functions) MUST NOT
affect the brand router unless explicitly coordinated. The shared helper
`aplicar_filtro_tienda_oficial` or equivalent internal function MAY be reused, but
the store ID MUST be hardcoded as a constant (`TPLINK_STORE_ID = 2645`) in the
brand router module, not read from any request param or config.

---

## Out of Scope

- Hardening the existing `/dashboard-ml/*` endpoints against store-filter
  manipulation (separate audit item).
- Multi-brand support (one brand per router approach — if a second brand is added,
  a new router is created following the same pattern).
