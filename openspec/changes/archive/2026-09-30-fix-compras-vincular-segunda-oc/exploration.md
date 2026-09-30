# Exploration: fix-compras-vincular-segunda-oc

## Exploration: Keep Vincular OC for a second ERP OC

### Current State

Backend already supports N OCs on one pedido. `pedidos_service.vincular_oc` INSERTs `pedido_compra_ocs` and does **not** replace the first-link header cache (`oc_comp_id` / `oc_bra_id` / `oc_poh_id`). Duplicate triple → 409. `tipo=servicio` → 409 and empty candidatas. POST `/administracion/compras/pedidos/{id}/vincular-oc` returns `PedidoCompraResponse` with `ocs[]`. List Pedidos already renders compact `#{oc_poh_id}` chips when `ocs.length > 1`.

Pedido **detail** UI does not. In `ModalPedidoDetalle.jsx` section "Orden de compra ERP" (~894–945), `pedido.oc_poh_id` is a binary branch:

- **set** → text `Vinculada a OC #{pedido.oc_poh_id}` (header only) + **Desvincular OC** (unlink-all). **No Vincular OC.**
- **unset** → "Sin OC…" + **Vincular OC** (`setShowVincularOCModal(true)`).

`ModalVincularOC` (~1190) still POSTs the existing endpoint. `handleVinculaOC` stores the POST body but the section still prints only header `oc_poh_id`. GET `/pedidos/{id}` selectinloads `ocs` (`PedidoCompraDetalle` inherits `ocs`); list path sets `ocs` via `_ocs_payload`. Detail `model_copy` does not call `_ocs_payload` explicitly — apply MUST confirm GET returns every triple.

Docs (`compras-guia-usuario.md` ~205) already say vincular **adds**. Operator cannot reach that from detail after the first OC.

### Affected Areas

- `frontend/src/components/compras/ModalPedidoDetalle.jsx` — hide/show branch; list linked OCs
- `frontend/src/components/compras/ModalPedidoDetalle.module.css` — action cluster if Vincular + Desvincular share the linked row
- `frontend/src/components/compras/ModalPedidoDetalle.test.jsx` — no current Vincular OC coverage
- `frontend/src/components/compras/ModalVincularOC.jsx` — reuse as-is
- `frontend/src/components/compras/TabPedidosCompra.jsx` — do not regress `#poh` chips
- `backend/app/routers/administracion_compras.py` — `obtener_pedido` ocs payload only if GET omits `ocs[]`
- `docs/modulos/compras-guia-usuario.md` — detail can add another OC
- `openspec/specs/vincular-oc/spec.md` — backend add-not-replace already specified; UI gap is not

Unchanged: `vincular_oc` rules, desvincular all-or-nothing, permissions.

### Approaches

1. **Unhide Vincular OC only** — keep printing header `oc_poh_id`.
   - Pros: smallest JSX
   - Cons: after a second link the operator still sees only the first OC (fails usability lock)
   - Effort: Low

2. **Unhide + list every linked OC in detail (recommended)** — show Vincular when `canGestionar && tipo !== 'servicio'`; render `ocs[]` (header fallback); keep Desvincular; reuse ModalVincularOC.
   - Pros: matches backend; operator sees the new OC; list chips untouched
   - Cons: small CSS for two actions
   - Effort: Low

3. **New permiso / granular unlink / new API**
   - Pros: none for this lock
   - Cons: out of scope
   - Effort: High

### Recommendation

Approach 2. Backend and modal already add. Fix the detail gate and the one-number display.

Apply later MUST branch from **main** (`sernafernando/pricing-app`), not from `feat/compras-pedidos-layout-y-alerta-factura` (#1348, already merged). This planning phase does not branch.

### Risks

- GET detail `ocs[]` empty while relation has two rows → list would look like one OC; prove GET or wire `_ocs_payload`
- Servicio with no OC currently still shows Vincular; lock hides it (modal already empty / POST 409)
- Desvincular remains unlink-all; operators may expect per-OC unlink (documented, out of scope)

### Ready for Proposal

Yes — product lock is complete; no further clarification.
