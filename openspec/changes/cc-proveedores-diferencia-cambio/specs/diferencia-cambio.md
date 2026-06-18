# Spec Delta — Diferencia de Cambio en Pedidos de Compra

**Change:** cc-proveedores-diferencia-cambio
**Capability:** diferencia-cambio
**Status:** draft

## Purpose

Surface the FX variance (diferencia de cambio) on USD purchase orders settled with ARS payments
(`actualizar_tc_pedido=False`, i.e. Caso B) so that the purchase order list and detail both show
the pending ARS difference and allow filtering by it. Resolution uses the existing
`resolver-varianza-tc` circuit without modification.

## Scope Boundaries

- **IN**: Caso B only — ARS OP paying a USD `PedidoCompra` with `actualizar_tc_pedido=False`.
- **OUT**: Caso A (`actualizar_tc_pedido=True`) — `calcular_varianza_tc` already returns 0 for
  Caso A; no display or badge is emitted.
- **OUT**: Caso C (USD OP → USD pedido at different TC) — separate future slice.
- **OUT**: DB schema changes — variance is a pure derivation; nothing is stored.
- **OUT**: New NC/ND resolution endpoints — `POST /pedidos/{id}/resolver-varianza-tc` is reused
  as-is.
- **OUT**: Changes to `calcular_saldo_pendiente_pedido` or CC histórico view.

---

## ADDED / CHANGED Requirements

### Requirement: REQ-FX-001 — Batch variance computation without N+1

**Priority:** must
**Type:** performance / functional

The backend MUST expose a function
`calcular_varianza_tc_batch(session, pedido_ids: list[int]) -> dict[int, Decimal]`
in `pedidos_service.py` that mirrors the pattern of `calcular_saldos_pendientes_batch` and
`calcular_tc_ponderado_pedido_batch`:

- Executes **one aggregated query per component** (non-reversal Caso-B imps, reversal Caso-B
  imps, non-reversal NCs, reversal NCs), grouped by `destino_id` (= pedido_id).
- MUST NOT issue any per-pedido sub-query or lazy relationship load.
- Returns `{pedido_id: varianza_tc_neta}` for every id in the input list; missing ids default to
  `Decimal("0")`.
- MUST reuse the same Caso-B filter as `calcular_varianza_tc`:
  `OrdenPago.actualizar_tc_pedido.is_(False)` and `Imputacion.moneda_imputada == "ARS"` on a
  USD pedido.
- Edge — `tipo_cambio_original IS NULL` (pre-migration pedidos): treat as
  `varianza_bruta = 0` for that pedido (no error).
- Edge — ARS pedido (no TC, no FX): batch returns `0` for that pedido (not an error).

#### Scenario: Batch returns correct variance for Caso-B orders

- GIVEN pedido A (USD, TC_original=1000) with one ARS imputacion of 1400 ARS
  (`actualizar_tc_pedido=False`)
- AND pedido B (USD, TC_original=1000) with one ARS imputacion of 1000 ARS
  (`actualizar_tc_pedido=False`)
- AND pedido C (ARS, no TC)
- WHEN `calcular_varianza_tc_batch(session, [A.id, B.id, C.id])` is called
- THEN result[A.id] == Decimal("-400") (ARS overpaid vs original)
- AND result[B.id] == Decimal("0")
- AND result[C.id] == Decimal("0")

#### Scenario: Batch issues no N+1 queries

- GIVEN a list of 50 pedido ids
- WHEN `calcular_varianza_tc_batch` is called
- THEN the SQLAlchemy query count MUST be ≤ 4 (one per component group-by), regardless of list size

#### Scenario: NULL tipo_cambio_original is safe

- GIVEN a pedido with `tipo_cambio_original = NULL` and ARS imputaciones
- WHEN `calcular_varianza_tc_batch` is called with that pedido's id
- THEN result for that id == Decimal("0") and no exception is raised

---

### Requirement: REQ-FX-002 — List endpoint exposes varianza_tc_neta per item

**Priority:** must
**Type:** functional / API contract

`GET /api/administracion/compras/pedidos` (router: `administracion_compras.py:298`) MUST:

- Call `calcular_varianza_tc_batch` for all pedido ids on the current page.
- Populate `varianza_tc_neta: Decimal | None` and `varianza_tc_pendiente: bool` on every
  `PedidoCompraResponse` item in the list.
- `varianza_tc_pendiente = abs(varianza_tc_neta) > VARIANZA_TC_THRESHOLD_ARS` (threshold = 1.00 ARS).
- No schema change required — `PedidoCompraResponse` already carries both fields.
- Response MUST include `moneda_varianza: "ARS"` (literal constant) alongside `varianza_tc_neta`
  so consumers never need to infer the currency.

#### Scenario: List response includes variance fields

- GIVEN a USD pedido in estado `pagado` with varianza_tc_neta = −400 ARS
- WHEN `GET /pedidos?page=1&page_size=20` is requested
- THEN the response item for that pedido contains
  `varianza_tc_neta = -400.00`, `varianza_tc_pendiente = true`, `moneda_varianza = "ARS"`

#### Scenario: Fully absorbed variance is not pending

- GIVEN a USD pedido whose resolver-varianza-tc was already applied (NC/ND imputated)
- WHEN `GET /pedidos` is requested
- THEN `varianza_tc_pendiente = false` and `varianza_tc_neta` is within ±1.00 ARS of zero

---

### Requirement: REQ-FX-003 — Server-side filter ?diferencial_cambio_pendiente=true

**Priority:** must
**Type:** functional / API contract

`GET /pedidos` MUST accept an optional query param `diferencial_cambio_pendiente: bool`.

When `diferencial_cambio_pendiente=true`:

- The filter MUST be applied **inside the main query** (not post-pagination) so that `total` and
  `pages` counts reflect the filtered set.
- Only pedidos with `estado IN ('pagado', 'pagado_parcial')` are eligible (FX variance on
  non-settled orders is irrelevant).
- The filter selects pedidos where `abs(varianza_tc_neta) > VARIANZA_TC_THRESHOLD_ARS`.
  Implementation detail: the batch-derived variance cannot be filtered in SQL directly; the
  service MUST pre-compute the eligible `pedido_ids` in a single aggregation query and then
  apply `PedidoCompra.id.in_(eligible_ids)` before the paginator runs.
- When `diferencial_cambio_pendiente=false` or absent, existing behavior is unchanged.

#### Scenario: Filter returns only pedidos with pending differential

- GIVEN 3 pagado pedidos: P1 (varianza −400, pendiente), P2 (varianza 0), P3 (varianza −0.50, below threshold)
- WHEN `GET /pedidos?diferencial_cambio_pendiente=true`
- THEN response contains only P1; total=1; P2 and P3 are excluded

#### Scenario: Pagination counts reflect the filter

- GIVEN 25 pedidos, 10 have `varianza_tc_pendiente=true`
- WHEN `GET /pedidos?diferencial_cambio_pendiente=true&page=1&page_size=5`
- THEN `total = 10`, `pages = 2`, and only 5 items are returned (not 25 total, not 20 remaining)

#### Scenario: Filter ignores non-settled estados

- GIVEN a pedido with `estado='aprobado'` and a large TC variance
- WHEN `GET /pedidos?diferencial_cambio_pendiente=true`
- THEN that pedido is NOT included in results

#### Scenario: Filter absent — no regression

- WHEN `GET /pedidos` with no filter params
- THEN all pedidos are returned (same as current behavior), varianza fields populated

---

### Requirement: REQ-FX-004 — Saldo display replaced by varianza_tc_neta in list and detail

**Priority:** must
**Type:** functional / UX

When `varianza_tc_pendiente=true` for a pedido row in `TabPedidosCompra.jsx`:

- The saldo column MUST display `varianza_tc_neta` formatted in ARS (e.g. "−$400,00 ARS") instead
  of the normal origin-currency saldo.
- The currency label "ARS" MUST be visible adjacent to the value.
- When `varianza_tc_pendiente=false`, the normal saldo is shown (no change in behavior).

In `ModalPedidoDetalle.jsx` (detail), the same replacement applies:

- When `varianza_tc_pendiente=true`, the saldo section displays `varianza_tc_neta` in ARS.
- The existing badge "Falta aplicar ND/NC por varianza TC" and "Resolver varianza TC" button
  remain unchanged.

Caso A (varianza is 0 by F2 definition) MUST NOT show any FX differential display or badge.

#### Scenario: Caso B with pending differential — list shows ARS variance

- GIVEN a list row with `varianza_tc_pendiente=true` and `varianza_tc_neta=-400`
- WHEN rendered in `TabPedidosCompra`
- THEN saldo cell shows "−$400,00 ARS" (or equivalent locale format)
- AND the badge "Falta aplicar NC/ND" is visible on that row

#### Scenario: No pending differential — list shows normal saldo

- GIVEN a list row with `varianza_tc_pendiente=false`
- WHEN rendered in `TabPedidosCompra`
- THEN saldo cell shows the normal origin-currency saldo (unchanged)
- AND no badge is rendered

#### Scenario: Caso A (actualizar_tc_pedido=True) — no differential display

- GIVEN a USD pedido paid via ARS OP with `actualizar_tc_pedido=True`
- WHEN rendered in list or detail
- THEN `varianza_tc_neta = 0`, `varianza_tc_pendiente = false`
- AND no FX badge is shown

---

### Requirement: REQ-FX-005 — Badge "Falta aplicar NC/ND" in list view

**Priority:** must
**Type:** functional / UX

`TabPedidosCompra.jsx` MUST render a badge (chip or tag) with text "Falta aplicar NC/ND" on any
row where `varianza_tc_pendiente=true`.

- The badge MUST be consistent in style with the existing badge in `ModalPedidoDetalle.jsx:910`.
- The badge MUST NOT appear when `varianza_tc_pendiente=false`.
- The existing badge in `ModalPedidoDetalle.jsx` is unchanged.

---

### Requirement: REQ-FX-006 — Filter control in TabPedidosCompra

**Priority:** must
**Type:** functional / UX

`TabPedidosCompra.jsx` MUST include a filter control (e.g. checkbox or toggle) labeled
"Diferencial de cambio pendiente" that, when activated:

- Adds `diferencial_cambio_pendiente=true` to the `GET /pedidos` request params.
- Clears and resets pagination to page 1.
- When deactivated, removes the param and resets pagination.

The filter is a server-side filter; no client-side post-filtering is performed.

---

### Requirement: REQ-FX-007 — Resolution via existing circuit; badge disappears after apply

**Priority:** must
**Type:** functional

`POST /pedidos/{id}/resolver-varianza-tc` is reused without modification.

After a successful call:

- `calcular_varianza_tc` (F2) for that pedido MUST return `varianza_tc_neta` within
  ±`VARIANZA_TC_THRESHOLD_ARS` (i.e. effectively 0 after NC/ND is imputated).
- Consequently `varianza_tc_pendiente = false`.
- The next `GET /pedidos` response for that pedido MUST show `varianza_tc_pendiente=false` and
  the ARS saldo display reverts to normal saldo.
- The badge disappears from both list and detail.
- The pedido MUST NOT appear in `?diferencial_cambio_pendiente=true` results.

No new endpoint is created for resolution. The existing `administracion.gestionar_ordenes_compra`
permission gate is unchanged.

#### Scenario: Resolution clears variance and badge

- GIVEN a pedido with `varianza_tc_neta=-400`, `varianza_tc_pendiente=true`
- WHEN `POST /pedidos/{id}/resolver-varianza-tc` is called successfully
- THEN `calcular_varianza_tc(session, pedido)` returns `varianza_tc_neta ≈ 0`
- AND `GET /pedidos?diferencial_cambio_pendiente=true` does NOT include that pedido
- AND the list row for that pedido shows normal saldo with no badge

---

## Edge Cases

### REQ-FX-EDGE-001 — tipo_cambio_original NULL (pre-migration pedidos)

- `calcular_varianza_tc_batch` MUST return `Decimal("0")` for any pedido with
  `tipo_cambio_original IS NULL`.
- No error, no badge, no FX display for those pedidos.

### REQ-FX-EDGE-002 — ARS pedido (no foreign currency)

- `calcular_varianza_tc_batch` MUST return `Decimal("0")` for any pedido with `moneda="ARS"`.
- No error, no badge.

### REQ-FX-EDGE-003 — Threshold boundary

- Variance of exactly `±1.00 ARS` → `varianza_tc_pendiente = false` (boundary is exclusive).
- Variance of `±1.01 ARS` → `varianza_tc_pendiente = true`.

---

## Non-Goals (explicit)

- Changing `calcular_saldo_pendiente_pedido` — pedido saldo in origin currency is untouched.
- Storing `varianza_tc_neta` in any DB column.
- New estado values (e.g. `pagado_diferencial_pendiente`).
- Linking existing supplier NCs manually — auto-resolver only (OQ-3 deferred).
- Extending to Caso C (USD OP → USD pedido, different TC) — separate slice (OQ-2 deferred).
