# Design: cc-proveedores-diferencia-cambio

> HOW (architecture). Tasks are a separate artifact. Grounded in the real code at
> `backend/app/services/pedidos_service.py`, `backend/app/routers/administracion_compras.py`,
> `frontend/src/components/compras/TabPedidosCompra.jsx`,
> `frontend/src/components/compras/ModalPedidoDetalle.jsx`.

## 1. Approach summary

Pure **surface + filter over F2** (`calcular_varianza_tc`, `pedidos_service.py:1150`). No
recompute, no new saldo formula, no schema change. Caso-B only (LOCKED decision 1). The
displayed saldo is **replaced** by `varianza_tc_neta` (ARS) when `varianza_tc_pendiente` is
true, otherwise the normal origin-currency saldo (LOCKED decision 2). The change has three
mechanical pieces:

1. A batch variance helper `calcular_varianza_tc_batch` mirroring the existing `*_batch`
   helpers (`resolver_tc_efectivo_pedido_batch:1078`, `calcular_tc_ponderado_pedido_batch:849`,
   `calcular_saldos_pendientes_batch:686`) — bounded query count, no N+1.
2. `listar_pedidos` (`administracion_compras.py:298`) calls the batch, populates
   `varianza_tc_neta` per item, and applies the new `?diferencial_cambio_pendiente=true`
   server-side filter with correct pagination.
3. Frontend: list badge + ARS variance in the saldo column (`TabPedidosCompra.jsx`), filter
   control in `FiltersBar`, and the explicit ARS amount reinforced next to the origin saldo in
   the detail (the detail badge already exists at `ModalPedidoDetalle.jsx:910`).

## 2. Architecture & layering

No new layer. We extend the existing 3 layers exactly where they already live:

| Layer | File | Change |
|---|---|---|
| Service (derivation) | `pedidos_service.py` | NEW `calcular_varianza_tc_batch`; NEW candidate-id helper for the filter |
| Router (orchestration) | `administracion_compras.py` | `listar_pedidos` calls batch + filter; `_pedido_response` already wired |
| Schema | `pedido_compra.py` | NONE — `varianza_tc_neta`/`varianza_tc_pendiente` already exist (`:130-131`) |
| Frontend | `TabPedidosCompra.jsx` | renderCell saldo replacement + badge; FiltersBar control; fetch param |
| Frontend (detail) | `ModalPedidoDetalle.jsx` | reinforce ARS amount next to saldo (badge exists) |

Boundary rule preserved: the variance stays a **pure derivation** (AD-8). The origin-currency
saldo formula (`calcular_saldo_pendiente_pedido:735`) and the CC histórico
(`cc_proveedor_service.calcular_saldo_por_moneda`) are **not touched** — they remain the
sources of truth for their respective questions.

## 3. Component: `calcular_varianza_tc_batch`

### 3.1 Signature & contract

```python
def calcular_varianza_tc_batch(
    session: Session,
    pedido_ids: list[int],
) -> dict[int, Decimal]:
    """
    F2 batch — varianza_tc_neta for N pedidos with a bounded query count (no N+1).
    Mirrors calcular_varianza_tc (single-order) exactly so list parity holds.
    Returns {pedido_id: Decimal}. Every input id is present; non-USD / no-Caso-B → Decimal('0').
    """
```

### 3.2 Query shape (mirrors the single-order F2's 4 subqueries, grouped by destino_id)

`calcular_varianza_tc` (single) issues, per order:
- `tc_efectivo = resolver_tc_efectivo_pedido(session, pedido)` (precedence ladder)
- Caso-B non-reversal SUM(monto_usd), Caso-B reversal SUM(monto_usd)
- NC-local non-reversal rows, NC-local reversal rows

The batch composes the SAME logic from already-batched primitives plus 2 grouped aggregations:

1. **TC efectivo, batched** — reuse `resolver_tc_efectivo_pedido_batch(session, pedido_ids)`
   (already exists, `:1078`). One/two queries total; handles the AD-2 precedence ladder
   (manual override → Caso-A weighted → `tipo_cambio_original`). For non-USD or no-TC orders it
   returns `None`.
2. **`tipo_cambio_original`, batched** — single `SELECT id, moneda, tipo_cambio_original FROM
   pedidos_compra WHERE id IN (...)`. (Can be merged with the TC efectivo load, but a separate
   small query is fine and explicit.)
3. **Caso-B USD totals, grouped** — ONE query, signed sum (non-reversal − reversal) so cancelled
   OPs net out, mirroring lines `:1204-1231`:
   ```python
   signed = sa_func.sum(case((Imputacion.es_reversal.is_(True), -Imputacion.monto_imputado),
                              else_=Imputacion.monto_imputado))
   select(Imputacion.destino_id, signed)
     .join(OrdenPago, OrdenPago.id == Imputacion.origen_id)
     .where(Imputacion.origen_tipo == "orden_pago",
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id.in_(pedido_ids),
            Imputacion.moneda_imputada == "USD",
            Imputacion.tipo_cambio.is_not(None),
            OrdenPago.actualizar_tc_pedido.is_(False))
     .group_by(Imputacion.destino_id)
   ```
   → `caso_b_usd_map[pedido_id]`.
4. **NC-local compensation, grouped** — ONE query returning per-destino signed ARS, mirroring
   `:1240-1276`. Because the sign depends on `NotaCreditoLocal.tipo` (debito → +, credito → −)
   AND on `es_reversal`, fold both into a single `CASE`:
   ```python
   signo = case((NotaCreditoLocal.tipo == "debito", 1), else_=-1)
   signed_nc = sa_func.sum(
       case((Imputacion.es_reversal.is_(True), -signo * Imputacion.monto_imputado),
            else_=signo * Imputacion.monto_imputado))
   select(Imputacion.destino_id, signed_nc)
     .join(NotaCreditoLocal, NotaCreditoLocal.id == Imputacion.origen_id)
     .where(Imputacion.origen_tipo == "nota_credito_local",
            Imputacion.destino_tipo == "pedido_compra",
            Imputacion.destino_id.in_(pedido_ids),
            Imputacion.moneda_imputada == "ARS")
     .group_by(Imputacion.destino_id)
   ```
   → `compensada_map[pedido_id]`.

Then in memory, per id (same arithmetic as `:1231-1278`):
```python
tc_ef = tc_efectivo_map[pid]               # None → varianza 0
if moneda[pid] != "USD" or tc_ef is None: result[pid] = Decimal("0"); continue
tc_orig = original_map[pid] if not None else tc_ef
bruta = (tc_ef - tc_orig) * caso_b_usd_map.get(pid, 0)
neta  = (bruta - compensada_map.get(pid, 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)
result[pid] = neta
```

**Query budget:** 4–5 queries total regardless of N (1 TC-original + the
`resolver_tc_efectivo_pedido_batch` internal 1–2 + 1 Caso-B + 1 NC). Bounded → AC6/NFR-001 met.

**Parity guarantee:** the in-memory arithmetic and the `quantize` are copied verbatim from the
single-order function. The pytest parity test (per AC1) asserts
`calcular_varianza_tc_batch(...)[id] == calcular_varianza_tc(...)` for the same orders.

## 4. Server-side filter on a derived value with correct pagination (the hard part)

### 4.1 Problem

`varianza_tc_pendiente` is NOT a column and NOT a single SQL expression we can cleanly put in a
`WHERE`: `tc_efectivo` itself can come from a manual override, a Caso-A weighted average, or the
approval snapshot (AD-2 ladder, resolved in `resolver_tc_efectivo_pedido_batch` partly in
Python). Embedding that ladder + the NC compensation + the threshold into one SQL predicate would
duplicate F2 logic in raw SQL — a second source of truth, exactly what we are avoiding. And
`_paginate` (`:173`) computes `total` via `COUNT(*)` over the statement subquery, so if we filter
only the current page's batch result, `total`/page counts are WRONG.

### 4.2 Chosen approach — candidate narrowing in SQL, then F2 over candidates, then paginate IDs

Two-stage filter that keeps F2 as the single source of truth AND keeps pagination correct:

**Stage 1 — SQL candidate query (cheap, narrows the universe).** When
`diferencial_cambio_pendiente is True`, run a dedicated id-only query that returns the candidate
set: USD orders, in the relevant estados, that have at least one Caso-B USD imputación (the only
orders that *can* have non-zero Caso-B variance). This is a single `SELECT DISTINCT
pedidos_compra.id` joined to imputaciones+ordenes_pago with the Caso-B predicate and the same
base filters (`estado`, `proveedor_id`, `empresa_id`, `desde`, `hasta`). NEW helper:

```python
def listar_pedido_ids_con_caso_b(session, *, estados, proveedor_id, empresa_id, desde, hasta) -> list[int]
```

This excludes the vast majority of rows (ARS orders, USD orders never paid by an ARS OP) without
ever computing variance for them.

**Stage 2 — F2 over candidates, filter, paginate.** Run `calcular_varianza_tc_batch(session,
candidate_ids)`, keep only ids where `abs(neta) > VARIANZA_TC_THRESHOLD_ARS`. The surviving ids are
the true filtered set. `total = len(survivors)`. Apply ORDER BY (created_at desc, id desc — to
match the default) + offset/limit **on the id list**, then load only the page's PedidoCompra rows
with `joinedload(empresa, proveedor)`. Finally compute the per-page batch values (saldo, tc_pond,
and reuse the already-computed variance) for `_pedido_response`.

```
if diferencial_cambio_pendiente:
    candidate_ids = listar_pedido_ids_con_caso_b(db, estados=ESTADOS_DIFERENCIAL, ...filters)
    var_map = calcular_varianza_tc_batch(db, candidate_ids)
    survivors = [pid for pid in candidate_ids
                 if abs(var_map[pid]) > VARIANZA_TC_THRESHOLD_ARS]
    survivors = _ordenar_por_created_desc(db, survivors)   # stable order matching default list
    total = len(survivors)
    page_ids = survivors[(page-1)*page_size : page*page_size]
    items = load_pedidos(db, page_ids)        # joinedload empresa/proveedor, preserve order
else:
    # unchanged existing path (stmt + _paginate)
```

**Estados covered (LOCKED decision 4):** `pagado` + `pagado_parcial`. Define
`ESTADOS_DIFERENCIAL = ("pagado", "pagado_parcial")`. When the filter is on, the explicit `estado`
query param (if present) intersects with this set; when off, behavior is unchanged.

**Cost:** Stage-1 is one indexed id query. Stage-2 is the 4–5 bounded batch queries over the
candidate set (NOT the whole table) + one page load. Worst case scales with the number of USD
orders that have Caso-B payments — a small slice of the table, acceptable and documented. If that
candidate set ever grows large, the documented next step is materializing the variance, but that
is explicitly OUT of scope (AD-8: no stored column).

**Why not pure-SQL variance?** Rejected: duplicates the AD-2 TC ladder + NC compensation in raw
SQL, creating a second source of truth that can silently diverge from `calcular_varianza_tc`.
**Why not page-scoped filtering?** Rejected: breaks `total`/pagination (AC2), shows fewer rows per
page than `page_size`, and the user cannot page through all pending orders.

## 5. Saldo replacement logic (LOCKED decision 2)

The displayed saldo is **replaced** by `varianza_tc_neta` (ARS) when `varianza_tc_pendiente`,
otherwise the normal origin-currency saldo. This is a **frontend display** decision, not a
backend field change:

- Backend keeps sending BOTH `saldo_pendiente` (origin currency, unchanged) and `varianza_tc_neta`
  / `varianza_tc_pendiente`. We do NOT overwrite `saldo_pendiente` server-side — other flows
  (`pendientes-pago`, OP creation) depend on the origin-currency saldo, and corrupting it would
  break them. The response stays honest; the **list view chooses what to render**.
- `_pedido_response` (`:225`) already derives `varianza_tc_pendiente = abs(neta) > threshold` when
  `varianza_tc_neta is not None`. `listar_pedidos` now passes the batch value, so list parity with
  detail (AC1) holds automatically.

**Frontend rendering rule (renderCell `monto` case, `TabPedidosCompra.jsx:481`):**
```
if (p.varianza_tc_pendiente) {
    // REPLACE: show varianza_tc_neta as the principal ARS figure + currency-explicit label.
    principal = formatCurrency(Number(p.varianza_tc_neta), 'ARS')  // e.g. -$400,00 ARS
    label     = "diferencial a regularizar"
} else {
    // existing origin-currency saldo dual rendering (unchanged).
}
```
Consistency: the same rule is reinforced in the detail next to the origin saldo (the badge at
`ModalPedidoDetalle.jsx:910` already shows the ARS amount; add the explicit ARS figure adjacent to
the saldo line so list and detail tell the same story).

## 6. Frontend changes

### 6.1 `TabPedidosCompra.jsx`
- **renderCell `monto`**: variance-replacement branch above. Currency explicit (`'ARS'`), sign
  preserved (`-400`). Reuse `formatCurrency`.
- **Badge in row**: when `p.varianza_tc_pendiente`, render a "Falta aplicar NC/ND" badge in the
  estado or monto cell, reusing the visual language from `ModalPedidoDetalle.jsx:910`
  (`TrendingUp` icon + Tesla token styling). Add a `styles.badgeDiferencial` class to the module
  CSS using design tokens (no hardcoded colors — `var(--...)`), mirroring `badgeVenceUrgente`.
- **FiltersBar control**: add a checkbox/toggle (or a select) "Solo con diferencial pendiente"
  bound to a new `filtroDiferencial` state. When on, set `params.diferencial_cambio_pendiente =
  true` in `fetchPedidos` (`:151`). Add `filtroDiferencial` to the page-reset effect deps
  (`:204`) so toggling resets to page 1.

### 6.2 `ModalPedidoDetalle.jsx`
- Badge already exists (`:910`). Add the explicit ARS `varianza_tc_neta` next to the origin-saldo
  line so detail mirrors the list's replacement semantics. No new fetch (detail already computes
  variance, `administracion_compras.py:482`).

## 7. Migration

**NONE.** Variance stays a pure derivation (AD-8); schema fields `varianza_tc_neta` /
`varianza_tc_pendiente` already exist on `PedidoCompraResponse` (`pedido_compra.py:130-131`). No
new column, no index needed beyond what exists (the Caso-B candidate query rides existing
`imputaciones(destino_tipo, destino_id)` / `origen` access patterns; confirm an index on
`imputaciones(destino_id)` exists during tasks — likely already present for FKs).

## 8. Permissions

Unchanged. `GET /pedidos` (list + new filter) gated by `administracion.ver_ordenes_compra`
(`:312`). `POST /pedidos/{id}/resolver-varianza-tc` reused as-is, gated by
`administracion.gestionar_ordenes_compra` (`:806`). No new endpoint (LOCKED decision 5).

## 9. ADR-style decisions

- **AD-D1 — Batch composes batched primitives, not raw inline SQL.** `calcular_varianza_tc_batch`
  reuses `resolver_tc_efectivo_pedido_batch` + 2 grouped aggregations, copying the single-order
  arithmetic verbatim. *Rationale:* guarantees list/detail parity and keeps F2 the single source
  of truth. *Rejected:* re-deriving the TC ladder in pure SQL (divergence risk).
- **AD-D2 — Server-side filter via SQL candidate narrowing + F2 over candidates + id pagination.**
  *Rationale:* correct `total`/pagination on a derived value without duplicating variance logic in
  SQL. *Rejected:* page-scoped filter (breaks pagination); pure-SQL variance predicate (second
  source of truth); stored variance column (violates AD-8, out of scope).
- **AD-D3 — Saldo replacement is a frontend display choice; backend response unchanged.**
  *Rationale:* `saldo_pendiente` in origin currency is depended on by OP/pending-pago flows;
  replacing it server-side would corrupt them. The list/detail render `varianza_tc_neta` (ARS)
  when pending. *Rejected:* overwriting `saldo_pendiente` in the response.
- **AD-D4 — Filter scope = `pagado` + `pagado_parcial`.** *Rationale:* LOCKED decision 4; these are
  the only states where a settled-in-origin order can still owe an FX difference.
- **AD-D5 — No migration.** Derived value (AD-8). Confirmed.

## 10. Risks & assumptions

- **`tipo_cambio_original` NULL** (pre-F1 / ARS orders): batch must fall back to `tc_efectivo`
  exactly like the single-order function (`:1232`), and short-circuit non-USD to `0`. Covered by
  the in-memory step in §3.2 and an explicit pytest (AC8).
- **Performance of the derived filter**: bounded by the candidate set size (USD orders with Caso-B
  payments), not the whole table. Documented; acceptable for the current PyME data volume. If it
  grows, materialization is the documented (out-of-scope) escape hatch.
- **ARS orders / no Caso-B**: variance `0`, no badge, never enter the candidate set — verified by
  test (AC8).
- **Caso-C NOT covered** (USD OP paying USD order at a different TC): F2 returns 0 for it; this
  slice only surfaces what F2 already computes (LOCKED decision 1). If production turns out to be
  Caso-C, that variance branch is a separate slice (OQ-2 in the proposal).
- **Threshold edge** (`|varianza| ≤ 1.00 ARS`): no badge, excluded from filter survivors — same
  `VARIANZA_TC_THRESHOLD_ARS` constant used everywhere (no second threshold).
- **Order stability**: the id pagination in Stage-2 must reproduce the default list order
  (created_at desc, id desc) so the filtered view is consistent with the unfiltered one.

## 11. Testability (pytest, strict TDD)

- **Parity**: `calcular_varianza_tc_batch[id] == calcular_varianza_tc(order)` across a fixture of
  Caso-B / NC-compensated / ARS / NULL-TC / Caso-A-override orders (AC1).
- **Query count**: assert the batch issues a bounded, N-independent number of queries (AC6) — use
  a query counter / `assert_num_queries`-style helper or SQL echo capture.
- **Filter correctness**: `?diferencial_cambio_pendiente=true` returns exactly the survivors;
  `total` equals the survivor count across pages; absent/false returns the full unfiltered set
  (AC2).
- **Edge cases**: NULL `tipo_cambio_original`, ARS order (variance 0, no badge), threshold edge
  (|var| ≤ 1.00 → excluded) (AC8).
- **Resolver round-trip**: after `POST /resolver-varianza-tc`, the order drops out of the filter
  and shows `varianza_tc_pendiente == false` on re-fetch (AC5).
- **Permissions**: list gated by `ver_ordenes_compra`, resolver by `gestionar_ordenes_compra`
  (AC7).

## 12. Decisions to confirm before tasks

1. **Filter control UI shape**: checkbox/toggle ("Solo con diferencial pendiente") vs a select
   option — defaulting to a toggle in `FiltersBar`. Confirm UX preference.
2. **Where the row badge lives**: monto cell vs estado cell. Default: monto cell, next to the
   replaced ARS figure (keeps the FX story in one place).
3. **`estado` param + filter interaction**: when the filter is on AND an explicit `estado` is
   chosen, intersect with `{pagado, pagado_parcial}` (default) vs let `estado` override. Default:
   intersect.
4. **Index check**: confirm an index exists on `imputaciones(destino_id)` (and the
   `origen_tipo/origen_id` access path) during tasks; add one only if missing (would then require a
   migration — the single possible exception to §7's "no migration").
