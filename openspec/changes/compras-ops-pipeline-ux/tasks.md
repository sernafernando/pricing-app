# Tasks: Compras Pipeline UX

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900–1400 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR0 → PR1 → PR2 → PR3 → PR4 |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 0 | Rebase upstream main (read-only) | tracker | `git merge-base --is-ancestor upstream/main HEAD` | N/A git | reset tracker |
| 1 | Model + chips | PR1←tracker | `pytest test_pedido_factura_documentos.py test_eje_procesal.py` | `alembic upgrade head` | downgrade `compras_044` |
| 2 | Alerts | PR2←PR1 | `pytest test_compras_alertas_service.py` | POST factura banner | revert PR2 |
| 3 | Depósito | PR3←PR2 | `pytest test_recepcion_deposito_endpoints.py` | pagado+CC AND | revert PR3 |
| 4 | Multi-OC | PR4←PR3 | `pytest test_vincular_oc_multi.py` | 2nd OC N blocks | downgrade `compras_043` |

## Phase 0: Rebase

- [x] 0.1 Rebase/merge upstream main (read-only) so facturas_documento/pedidos_documento exist (PRs 1314/1316/1317) before seed Alembic. Test: columns present.

## Phase 1: PR1 model + visibility

- [x] 1.1 RED `backend/tests/unit/test_pedido_factura_documentos.py`: empty 422; `A-1; A-2; ;A-3` → 3; ERP ≠ cargada.
- [x] 1.2 GREEN `backend/alembic/versions/compras_044_pipeline_tipo_responsable_facturas.py` + `backend/app/models/pedido_factura_documento.py` + `backend/app/models/pedido_compra.py`. Test: seed; raw kept.
- [x] 1.3 `backend/app/services/pedidos_service.py` + `backend/app/schemas/pedido_compra.py`. Test: default mercadería; PM PATCH tipo 403; backfill `creado_por_id`.
- [x] 1.4 POST/DELETE factura in `backend/app/routers/administracion_compras.py`. Test: 201; 2m 204 / 6m 409.
- [x] 1.5 `eje_procesal` + chips in `frontend/src/components/compras/TabPedidosCompra.jsx` + `frontend/src/components/compras/ModalPedidoDetalle.jsx`. Test: `n_a_servicio` / `por_recibir`.
- [x] 1.6 `backend/app/schemas/orden_pago.py` `pedidos_numeros` + `frontend/src/components/compras/TabOrdenesPago.jsx`. Test: two `P-…`; `a_cuenta` empty. Docs `docs/modulos/compras-guia-usuario.md`.

## Phase 2: PR2 alerts

- [x] 2.1 RED `backend/tests/unit/test_compras_alertas_service.py`: copy `P-…`+proveedor+nº not `pedidos_documento`; fan-out titular∪sub-PM∪Admin∪Gerente.
- [x] 2.2 GREEN `backend/app/services/compras_alertas_service.py`. Test: per-user OK; empty nº no alert.
- [x] 2.3 `backend/app/api/endpoints/notificaciones.py` PATCH ok + snooze routes; hide mark+1h. Test: 10:00/10:20 until 11:00.
- [x] 2.4 Faltantes → `responsable_id` + `faltantes_texto`; G31 `deposito.recibir_mercaderia`. Test: empty 422; D3 no alert.
- [x] 2.5 `frontend/src/components/AppLayout.jsx` stack `compras.*`; OK→DESCARTADA. Test: banner+bell; undo retracts; no email.

## Phase 3: PR3 Depósito

- [ ] 3.1 AND `q_proveedor|q_numero|q_factura|q_empresa` in `backend/app/routers/administracion_compras.py`. Test: Acme∩FA-1.
- [ ] 3.2 `backend/app/schemas/recepcion.py` + `backend/app/services/recepcion_service.py`: undo; optional obs/photo; `faltantes_texto` required. Test: undo→pagado/CC; controlado 409.
- [ ] 3.3 `frontend/src/components/compras/TabRecepcionDeposito.jsx` + `frontend/src/hooks/useRecepcionDeposito.js`: pagado+CC; hide saldo 0; Docs=adjuntos; `?focus=observaciones`. Test: RTL.
- [ ] 3.4 Servicio 409 on recepción. Test: `n_a_servicio`.

## Phase 4: PR4 multi-OC

- [ ] 4.1 RED `backend/tests/integration/test_vincular_oc_multi.py`: add-not-replace; dup/servicio 409; partial 422.
- [ ] 4.2 GREEN `backend/alembic/versions/compras_043_pedido_compra_ocs.py` + `backend/app/models/pedido_compra_oc.py`. Test: first link kept.
- [ ] 4.3 `backend/app/services/pedidos_service.py` INSERT relation+header. Test: second kept; 403/404/supplier 409.
- [ ] 4.4 `backend/app/services/recepcion_service.py` controlado iff all OCs. Test: 1/2 open; last → controlado.
- [ ] 4.5 `frontend/src/components/compras/TabRecepcionDeposito.jsx` + `frontend/src/components/compras/ModalVincularOC.jsx` N blocks; servicio empty. Test: RTL 2 blocks.

## Phase 5: Verify

- [ ] 5.1 Confirm `docs/modulos/compras-guia-usuario.md` in-app only; no ERP multi-factura; `aprobado` kept; diffs clean.
