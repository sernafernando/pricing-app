# Design: Keep Vincular OC for a second ERP OC

## Technical Approach

Frontend-only unless GET detail omits `ocs[]`. Unhide **Vincular OC** independently of `oc_poh_id`. List every linked identity. Reuse `ModalVincularOC` and `POST .../vincular-oc`. Specs: detail button + detail list (`vincular-oc`); list `#poh` chips (`pedidos-compra`) stay as today.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|----------|---------|----------|--------|
| Button gate | `!oc_poh_id` vs `canGestionar && tipo !== 'servicio'` | First hides add-another | **Permission + not servicio** |
| Where to render Vincular | Empty branch only vs both branches | Empty-only is the bug | **Both: empty hint + linked row** |
| How to list OCs | Header only vs `ocs[]` vs union | Header hides N>1 | **`ocs[]` if length>0 else header triple** |
| After POST | `setPedido(body)` only vs also `fetchDetalle` | Body has `ocs[]` via `_pedido_response` | **setPedido + fetchDetalle** so GET and events match |
| GET `ocs[]` | Trust `model_validate` vs `_ocs_payload` | List already uses payload | **Prove GET; if empty for N>1, add `_ocs_payload` in `obtener_pedido` only** |
| Desvincular | Per-OC vs all | Product lock | **Unchanged unlink-all** |
| CSS | New classes vs wrap existing buttons | Two actions in `facturaVinculada` flex | **Small action cluster; reuse `btnPrimaryInline` / `btnGhost`** |
| Apply git | This #1348 branch vs **main** | #1348 already merged | **New branch from main** |

## Data Flow

```
canGestionar && tipo !== 'servicio'
        │
        ├── Vincular OC ──► ModalVincularOC
        │                      │
        │                      POST /pedidos/{id}/vincular-oc
        │                      │
        │                      200 PedidoCompraResponse { ocs[], oc_poh_id first-cache }
        │                      │
        │                      handleVinculaOC → setPedido + fetchDetalle
        │
        └── (if any link) Desvincular OC ──► DELETE .../desvincular-oc (all links)

Display identities:
  ocs.length > 0 ? ocs : (oc_poh_id ? [{header triple}] : [])
```

`fetchOcDetalle` may keep using header `oc_poh_id` (existing first-OC breakdown). Out of scope to split that table per OC; Depósito already has per-OC blocks.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/compras/ModalPedidoDetalle.jsx` | Modify | Gate + list all OCs; keep modal/POST; after link refetch |
| `frontend/src/components/compras/ModalPedidoDetalle.module.css` | Modify | Cluster Vincular + Desvincular on the linked row |
| `frontend/src/components/compras/ModalPedidoDetalle.test.jsx` | Modify | Button + list scenarios |
| `frontend/src/components/compras/TabPedidosCompra.test.jsx` | Read (run) | Compact `#poh` regression |
| `frontend/src/components/compras/ModalVincularOC.jsx` | Unchanged | Existing POST |
| `backend/app/routers/administracion_compras.py` | Modify **only if** GET omits `ocs[]` | `"ocs": _ocs_payload(pedido)` on `obtener_pedido` |
| `docs/modulos/compras-guia-usuario.md` | Modify | Detail can Vincular another OC; desvincular still all |

## Interfaces / Contracts

No new API. Linked identities:

```js
const linkedOcs =
  Array.isArray(pedido.ocs) && pedido.ocs.length > 0
    ? pedido.ocs
    : pedido.oc_poh_id != null
      ? [{ oc_comp_id: pedido.oc_comp_id, oc_bra_id: pedido.oc_bra_id, oc_poh_id: pedido.oc_poh_id }]
      : [];
```

Show **Vincular OC** iff `canGestionar && pedido.tipo !== 'servicio'`.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Button visible with `oc_poh_id`; hidden servicio / no permiso; two `ocs` both listed | `ModalPedidoDetalle.test.jsx` |
| Unit | List `#poh` chips `ocs.length > 1` | existing `TabPedidosCompra.test.jsx` |
| Unit | Modal still POSTs `vincular-oc` | existing `ModalVincularOC.test.jsx` (no change unless broken) |
| Integration | Add-not-replace already covered | `test_vincular_oc_multi.py` (run, no new backend cases unless GET `ocs` gap) |
| E2E | N/A | jsdom text/roles enough |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration. Apply: branch from **main**, PR to `sernafernando/pricing-app` **main**. Do not branch from `feat/compras-pedidos-layout-y-alerta-factura`.

## Open Questions

- None — GET `ocs[]` is an apply-time proof, not a product question.
