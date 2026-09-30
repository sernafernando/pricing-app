# Proposal: Keep Vincular OC for a second ERP OC

## Intent

Backend already links a second ERP OC (add, not replace). Pedido **detail** hides **Vincular OC** once `oc_poh_id` is set. After a second link it still prints only the first header number. Restore the action and list every linked OC.

## Scope

### In Scope

- Keep **Vincular OC** visible when `administracion.gestionar_ordenes_compra` and `tipo !== servicio`, even if `oc_poh_id` is set
- Reuse `ModalVincularOC` + existing `POST .../vincular-oc`
- Detail lists every linked OC (`ocs[]` and/or header), not only the first `oc_poh_id`
- Docs: detail can add another OC
- Tests: button, multi-OC list, servicio/permiso hides
- Do not regress Pedidos list compact `#poh` chips when `ocs.length > 1`

### Out of Scope

- New permiso; candidate-rule changes; granular desvincular; `vincular_oc` service; new endpoint/modal

## Capabilities

### New Capabilities

None

### Modified Capabilities

- `vincular-oc`: detail keeps Vincular OC for another link; lists every linked OC
- `pedidos-compra`: lock list compact `#poh` chips when `ocs.length > 1`

## Approach

Show Vincular OC when `canGestionar && tipo !== 'servicio'` in empty **and** linked branches. Linked branch renders `ocs[]`, else the header triple. Desvincular stays. If GET `/pedidos/{id}` omits `ocs[]` for N>1, set `_ocs_payload` (only if proven).

**Apply later** MUST branch from **`main`** (`sernafernando/pricing-app`), not from `feat/compras-pedidos-layout-y-alerta-factura` (#1348, merged). This planning phase does **not** branch, commit, or push. PR target: **main** (Gabe override, #1347/#1348).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `ModalPedidoDetalle.jsx` | Modified | Unhide Vincular OC; list all OCs |
| `ModalPedidoDetalle.module.css` | Modified | Action cluster if needed |
| `ModalPedidoDetalle.test.jsx` | Modified | Visibility + multi-OC list |
| `TabPedidosCompra.test.jsx` | Unchanged (run) | Compact `#poh` chips |
| `administracion_compras.py` | Modified only if GET omits `ocs[]` | `_ocs_payload` on detail |
| `compras-guia-usuario.md` | Modified | Vincular another OC from detail |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| GET detail drops `ocs[]` | Med | Prove GET; else `_ocs_payload` |
| Operators expect per-OC unlink | Low | Docs already say all-or-nothing |
| Servicio currently shows Vincular with no OC | Low | Hide per lock |

## Rollback Plan

Revert the PR on **main**. No schema. No permission seed.

## Dependencies

Landed multi-OC backend. Apply base: **main**, not this worktree’s #1348 branch.

## Success Criteria

- [ ] Mercadería + `canGestionar` + one OC still sees **Vincular OC**
- [ ] Servicio and missing permiso never show it
- [ ] After a second link, detail shows both OC numbers
- [ ] List `#poh` chips when `ocs.length > 1` still pass
- [ ] Desvincular still removes every link
