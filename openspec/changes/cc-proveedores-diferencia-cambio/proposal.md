# Proposal: cc-proveedores-diferencia-cambio

## 1. Problem

A USD purchase order (`PedidoCompra`) settled in ARS at an exchange rate that differs
from the order's original TC produces an FX difference (diferencia de cambio). The two
views of that order disagree:

- **CC histórico (correct, source of truth):** shows the real ARS balance (e.g. **−400 ARS**).
  `cc_proveedor_service.calcular_saldo_por_moneda` (`backend/app/services/cc_proveedor_service.py:508`)
  sums each ledger movement at the TC locked when it was entered: cargo 1000 USD @ TC 1000 = 1000 ARS,
  pago 1000 USD @ TC 1400 = 1400 ARS → saldo −400 ARS.
- **Vista del pedido (wrong, shows 0):** `pedidos_service.calcular_saldo_pendiente_pedido`
  (`backend/app/services/pedidos_service.py:735`) and the batch variant
  (`pedidos_service.py:686`) compute `saldo = monto − imputado` **in the order's native
  currency**, ignoring `imputacion.tipo_cambio`. A USD order fully paid in USD shows
  `saldo = 0` even when the ARS pesos actually moved differ.

### Root cause

The two figures answer different questions and that is **by design**:
- Pedido saldo (moneda origen): "was the agreed amount paid in the order's currency?" → 0.
- CC histórico: "how many pesos did we actually exchange with this supplier?" → −400.

The −400 ARS gap is the **diferencia de cambio**, and it is already computed today by the
F2 circuit `pedidos_service.calcular_varianza_tc` (`pedidos_service.py:1150`) as
`varianza_tc_neta` (a pure derivation, never stored). The detail modal already surfaces it
(`ModalPedidoDetalle.jsx:910`, badge "Falta aplicar ND/NC por varianza TC" + "Resolver
varianza TC" button), and the resolver endpoint
`POST /pedidos/{id}/resolver-varianza-tc` (`administracion_compras.py:806`) already
auto-creates and imputes the absorbing NC/ND.

### Current-state gap

1. The order list (`GET /pedidos`, `administracion_compras.py:298`) deliberately leaves
   `varianza_tc_neta = None` to avoid N+1, so **the list shows neither the FX difference
   nor the badge** — only the detail modal does.
2. There is **no way to find** the orders that look settled in origin currency but still
   carry a pending FX difference. No filter, no search.

## 2. Goal / Success

After this change:
- The order **list and detail** make the pending FX difference visible the way the histórico
  already does (the user sees the −400, not a misleading 0).
- A **badge** ("Falta aplicar NC/ND") appears in the **list** rows, not only in the detail.
- A **filter/search** (`?diferencial_cambio_pendiente=true`) finds exactly the orders that
  are settled in origin currency but still owe an FX-difference NC/ND.
- Applying/linking the NC/ND drives the difference to 0 by **reusing the existing F2
  resolver circuit** — no new movement type, no new saldo formula.

## 3. Approach — surface + filter over F2 (no recompute)

This is fundamentally a **visibility + filtering** change. The variance number already
exists (`calcular_varianza_tc` → `varianza_tc_neta`), the response schema already carries
it (`PedidoCompraResponse.varianza_tc_neta` / `.varianza_tc_pendiente`, derived in
`_pedido_response` at `administracion_compras.py:225`), the badge component exists, and the
resolver endpoint exists. We do **not** recompute saldo and we do **not** duplicate variance
logic.

The only real engineering is making F2 efficient for N rows in the list (avoid N+1) and
wiring the filter, badge, and list column.

### 3.1 Backend changes

1. **Batch variance** — add `pedidos_service.calcular_varianza_tc_batch(session, pedido_ids)`
   mirroring the existing `calcular_saldos_pendientes_batch` /
   `calcular_tc_ponderado_pedido_batch` pattern (aggregated queries, no per-row loop).
   Returns `{pedido_id: varianza_tc_neta}`.
2. **Expose in list** — in `listar_pedidos` (`administracion_compras.py:298`) call the batch
   and pass `varianza_tc_neta=` into `_pedido_response` per item. `_pedido_response` already
   derives `varianza_tc_pendiente = abs(neta) > VARIANZA_TC_THRESHOLD_ARS` (1.00 ARS), so no
   schema change is needed.
3. **Filter** — add `diferencial_cambio_pendiente: Optional[bool] = Query(None)` to
   `listar_pedidos`. When `true`, return only orders whose `varianza_tc_pendiente` is true.
   Because the variance is a derivation (not a column), the filter is applied over the batch
   result for the page. (Open question OQ-4 covers whether it must filter the full dataset
   server-side before pagination — see Risks.)
4. **Display field** — decide whether the list/detail show the FX difference as the order's
   saldo or as a distinct field "diferencial de cambio a regularizar" alongside the
   origin-currency saldo (OQ-1). Default proposal: **keep `saldo_pendiente` in origin
   currency (0 USD) and show `varianza_tc_neta` as a separate ARS indicator** ("diferencial
   −400 ARS"), because the histórico and the pedido answer different questions and conflating
   them would corrupt the origin-currency saldo other flows depend on.

### 3.2 Frontend changes

1. **List badge** — `TabPedidosCompra.jsx`: add a badge in the row when
   `varianza_tc_pendiente === true`, reusing the same label/visual language already used in
   `ModalPedidoDetalle.jsx:910`.
2. **Filter control** — add `diferencial_cambio_pendiente` to the `FiltersBar` in
   `TabPedidosCompra.jsx`, wired to the new query param.
3. **FX difference display** — show `varianza_tc_neta` (the −400) as the "diferencial de
   cambio a regularizar" indicator in the list and reinforce it in the detail (detail already
   has the badge; add the explicit ARS amount next to the origin-currency saldo).

### 3.3 Endpoints affected

- `GET /pedidos` (`administracion_compras.py:298`) — new `diferencial_cambio_pendiente`
  filter + `varianza_tc_neta` populated via batch. Permission unchanged
  (`administracion.ver_ordenes_compra`).
- `POST /pedidos/{id}/resolver-varianza-tc` (`administracion_compras.py:806`) — reused
  as-is. Permission `administracion.gestionar_ordenes_compra`.

## 4. Scope

### In scope (single slice — surface + filter)
- `calcular_varianza_tc_batch` (new batch helper).
- `varianza_tc_neta` exposed in `GET /pedidos` list responses.
- `?diferencial_cambio_pendiente=true` filter.
- List badge + FX-difference indicator in `TabPedidosCompra.jsx`.
- FX-difference amount shown in detail next to origin-currency saldo.

### Out of scope
- New DB columns / migrations (variance stays a pure derivation — AD-8).
- Changing the origin-currency saldo formula (`calcular_saldo_pendiente_pedido` untouched).
- Changing the CC histórico calculation (it is the source of truth; do not touch).
- A new NC/ND linking mechanism beyond the existing resolver (unless OQ-3 says otherwise).
- Extending F2 to cover **Caso-A / Caso-C** (USD OP paying a USD order at a different TC) —
  pending OQ-2 confirmation. The exploration shows `calcular_varianza_tc` today only covers
  Caso-B (ARS OP, `actualizar_tc_pedido=False`). If the real production scenario is Caso-C,
  that variance branch is a **separate slice** and must be confirmed before specs.

## 5. Risks

- **N+1 in the list.** The batch must be a single aggregated query (or a fixed small number),
  matching the existing `*_batch` helpers. F2 currently runs 4 sub-queries per order
  (Caso-B non-rev/rev + NC non-rev/rev); batching requires grouping these by `destino_id`.
- **`tipo_cambio_original` NULL** on pre-F1 or ARS orders. `calcular_varianza_tc` already
  guards (`moneda != "USD"` → 0; NULL TC falls back to `tc_efectivo`). The batch must
  preserve these guards.
- **Caso-B vs Caso-C (BLOCKING for the variance side).** If the real scenario is a USD OP
  paying a USD order at a different TC, today's F2 returns 0 for it and the badge/filter would
  show nothing. Must confirm OQ-2 before specs; surface+filter still ships, but it only
  reveals what F2 already computes.
- **Filter vs pagination.** If `diferencial_cambio_pendiente=true` is applied only over the
  current page's batch result, total/pagination counts will be wrong. May need a server-side
  pre-filter (candidate-ID query) before pagination (OQ-4).
- **Double-counting** if an order has both Caso-B and (future) Caso-C payments — relevant only
  if the variance branch is extended.

## 6. Acceptance criteria

1. `GET /pedidos` returns `varianza_tc_neta` and `varianza_tc_pendiente` for every item,
   matching the value the detail endpoint returns for the same order (parity test).
2. `GET /pedidos?diferencial_cambio_pendiente=true` returns only orders with
   `varianza_tc_pendiente === true`; `=false`/absent returns all.
3. List response for the histórico's −400 example shows the FX difference (−400 ARS) as the
   "diferencial de cambio a regularizar" indicator, with origin-currency saldo still 0 USD.
4. The list row renders the "Falta aplicar NC/ND" badge iff `varianza_tc_pendiente` is true.
5. After `POST /pedidos/{id}/resolver-varianza-tc`, a re-fetch of the list shows
   `varianza_tc_pendiente === false` and the FX-difference indicator at 0 for that order.
6. Batch variance for N orders issues a bounded, N-independent number of queries (no N+1) —
   verified by query count.
7. Permissions unchanged: list gated by `administracion.ver_ordenes_compra`, resolver by
   `administracion.gestionar_ordenes_compra`.
8. Strict TDD: pytest covers batch parity with single-order F2, the filter, NULL
   `tipo_cambio_original`, ARS orders (variance 0, no badge), and the threshold edge
   (|varianza| ≤ 1.00 ARS → no badge).

## 7. Proposal question round (confirm before specs)

1. **Display (OQ-1):** Does the order saldo get **replaced** by the ARS figure (−400), or do
   we show **both** (origin saldo 0 USD + "diferencial de cambio −400 ARS")? Proposal default
   = show both (don't corrupt the origin-currency saldo).
2. **Scenario (OQ-2, BLOCKING):** Is the real production case Caso-B (ARS OP paying a USD
   order, already computed by F2) or Caso-C (USD OP paying a USD order at a different TC, **not**
   computed today)? If Caso-C, extending the variance branch is a separate slice.
3. **Linking (OQ-3):** Does "vincular NC/ND" always mean the existing auto-resolver
   (`resolver-varianza-tc` creates the NC/ND), or do you also want to manually pick an existing
   supplier NC/ND and apply it to the order?
4. **Filter/states (OQ-4):** The filter lives in `TabPedidosCompra`'s FiltersBar — which order
   states must it cover (`pagado`, `pagado_parcial`, all)? And must the filter pre-filter the
   full dataset server-side so pagination counts are correct, or is page-scoped filtering
   acceptable for the first slice?
