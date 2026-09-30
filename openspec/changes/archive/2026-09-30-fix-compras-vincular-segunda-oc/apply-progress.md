# Apply Progress: fix-compras-vincular-segunda-oc

**Change**: fix-compras-vincular-segunda-oc
**Mode**: Standard (no `openspec/config.yaml` tdd flag; strict_tdd not enabled)
**Branch**: `fix/compras-vincular-segunda-oc` (from `upstream/main`; not `feat/compras-pedidos-layout-y-alerta-factura`)
**Delivery**: single PR to `sernafernando/pricing-app` **main** (Low risk, Decision needed: No). Apply did not commit, push, or open a PR.
**Work unit**: `apply-all` — Unhide Vincular OC + list every linked OC

## Completed Tasks

- [x] 1.1 Vincular OC when `canGestionar && tipo !== 'servicio'` on empty **and** linked branches (`canVincularOc`). Reuses `setShowVincularOCModal(true)` + `ModalVincularOC`.
- [x] 1.2 `linkedOcTriples`: `ocs[]` if length>0 else header triple. Linked row prints every `#{oc_poh_id}`. Desvincular still `desvinculaOc` (all-or-nothing).
- [x] 1.3 `handleVinculaOC`: `setPedido(updatedPedido)` then `await fetchDetalle()`.
- [x] 1.4 `.ocActionCluster` + `flex-wrap` on `.facturaVinculada` / `.facturaNoVinculada`. Reuse `btnPrimaryInline` / `btnGhost`. No new absolute/fixed on the cluster.
- [x] 2.1 **SKIPPED** — GET already returns `ocs`. Proof: `obtener_pedido` `selectinload(PedidoCompra.ocs)` + `PedidoCompraDetalle.model_validate` (inherits `ocs: list[PedidoCompraOcLink]`); `model_copy` does not overwrite `ocs`. Dummy two-row `ocs` → poh_ids `{100, 200}`. Router unchanged.
- [x] 3.1 Mercadería + `oc_poh_id` + permiso → Vincular OC + Desvincular OC + `#100`.
- [x] 3.2 `ocs` `#100` and `#200` both listed; Vincular still visible.
- [x] 3.3 Servicio and missing permiso hide Vincular OC; mercadería with no OC still shows it.
- [x] 3.4 TabPedidosCompra compact `#poh` regression (read-only).
- [x] 3.5 ModalVincularOC + `test_vincular_oc_multi.py` (read-only; 2.1 did not add a GET assertion).
- [x] 4.1 `compras-guia-usuario.md`: detail Vincular OC stays available to add another; Desvincular still all-or-nothing.

## Work Unit Evidence

### Unit apply-all — Unhide Vincular OC + list all linked OCs

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd frontend && pnpm exec vitest run src/components/compras/ModalPedidoDetalle.test.jsx src/components/compras/TabPedidosCompra.test.jsx src/components/compras/ModalVincularOC.test.jsx && pnpm exec eslint src/components/compras/ModalPedidoDetalle.jsx` → **29 passed** (3 files); eslint exit 0. Backend read-only: `pytest tests/integration/test_vincular_oc_multi.py -q` → **11 passed** in 5.18s. |
| Runtime harness command/scenario and exact result | N/A — jsdom roles/text; GET `ocs` proven via `PedidoCompraDetalle.model_validate` on a two-row dummy (`poh_ids={100,200}`); no new runtime/browser boundary. |
| Rollback boundary | Revert `ModalPedidoDetalle.jsx`, `ModalPedidoDetalle.module.css`, `ModalPedidoDetalle.test.jsx`, `docs/modulos/compras-guia-usuario.md`. Router untouched. |

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `frontend/src/components/compras/ModalPedidoDetalle.jsx` | Modified | Gate + list all OCs; setPedido + fetchDetalle after link |
| `frontend/src/components/compras/ModalPedidoDetalle.module.css` | Modified | flex-wrap linked row; `.ocActionCluster` |
| `frontend/src/components/compras/ModalPedidoDetalle.test.jsx` | Modified | Button + multi-OC + servicio/permiso/empty cases |
| `docs/modulos/compras-guia-usuario.md` | Modified | Detail can Vincular another OC; desvincular still all |
| `backend/app/routers/administracion_compras.py` | Unchanged | 2.1 skipped |

## Deviations from Design

None — implementation matches design. 2.1 skip is the designed proof path.

## Issues Found

None. Authored production+test+docs diff: 4 files, 164 insertions, 37 deletions (201 authored lines; under 400).

## Workload / PR Boundary

- Mode: single PR to `main` (apply did not commit, push, or open a PR)
- Current work unit: apply-all
- Boundary: planning-complete → this apply (detail UI + tests + docs; no router)
- Estimated review budget impact: Low (201 authored lines)

## Status

11/11 tasks complete. Ready for verify.
