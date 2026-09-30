# Tasks: Keep Vincular OC for a second ERP OC

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 80–180 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR to main |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Unhide Vincular OC + list all linked OCs | PR 1 → main (branch from **main**, not #1348) | `pnpm exec vitest run src/components/compras/ModalPedidoDetalle.test.jsx src/components/compras/TabPedidosCompra.test.jsx src/components/compras/ModalVincularOC.test.jsx` | N/A — jsdom roles/text; backend already proven | Revert ModalPedidoDetalle + docs (+ router only if `_ocs_payload` added) |

**Apply git (do not run in planning):** `git fetch` upstream/main, branch `fix/compras-vincular-segunda-oc` from **main**, PR to `sernafernando/pricing-app` **main**.

## Phase 1: Detail UI

- [x] 1.1 In `frontend/src/components/compras/ModalPedidoDetalle.jsx` show **Vincular OC** when `canGestionar && pedido.tipo !== 'servicio'`, including when `oc_poh_id` is set. Keep `setShowVincularOCModal(true)` + existing `ModalVincularOC` / POST. Hide the button for `tipo=servicio`.
- [x] 1.2 In the same file, list every linked OC from `ocs[]` (else header triple). Do not print only `pedido.oc_poh_id` when more than one OC exists. Keep **Desvincular OC** all-or-nothing.
- [x] 1.3 In `handleVinculaOC`, `setPedido` from POST body and `fetchDetalle` so the new OC appears immediately.
- [x] 1.4 In `frontend/src/components/compras/ModalPedidoDetalle.module.css` cluster Vincular + Desvincular on the linked row (reuse `btnPrimaryInline` / `btnGhost`).

## Phase 2: GET ocs (only if proven)

- [x] 2.1 SKIPPED — GET already returns both triples. `obtener_pedido` `selectinload(PedidoCompra.ocs)` + `PedidoCompraDetalle.model_validate` (inherits `ocs`); dummy two-row `ocs` yields poh_ids `{100, 200}`. Did not add `_ocs_payload` on `obtener_pedido`.

## Phase 3: Tests

- [x] 3.1 In `frontend/src/components/compras/ModalPedidoDetalle.test.jsx`: mercadería + `oc_poh_id` + permiso → **Vincular OC** visible (Detail Vincular OC stays available — one OC).
- [x] 3.2 Same file: `ocs` `#100` and `#200` → both listed, not only `#100` (Pedido detail lists every linked OC — two OCs).
- [x] 3.3 Same file: `tipo=servicio` and missing permiso hide **Vincular OC**; mercadería with no OC still shows it.
- [x] 3.4 Run `frontend/src/components/compras/TabPedidosCompra.test.jsx` (read-only): compact `#poh` when `ocs.length > 1`; single OC has no extra poh labels.
- [x] 3.5 Run `frontend/src/components/compras/ModalVincularOC.test.jsx` (read-only) and `backend/tests/integration/test_vincular_oc_multi.py` (read-only) unless 2.1 added a GET assertion.

## Phase 4: Docs

- [x] 4.1 In `docs/modulos/compras-guia-usuario.md` (~varias OCs): from pedido **detalle**, **Vincular OC** stays available to add another OC; **Desvincular OC** still removes all.

## Definition of Done / Verification

`cd frontend && pnpm exec vitest run src/components/compras/ModalPedidoDetalle.test.jsx src/components/compras/TabPedidosCompra.test.jsx src/components/compras/ModalVincularOC.test.jsx && pnpm exec eslint src/components/compras/ModalPedidoDetalle.jsx`
