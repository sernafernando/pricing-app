# Tasks: Compras Pipeline Reqs Closure

## Baseline — do not regress

Do not amend `openspec/changes/compras-pipeline-chicho-review-fixes`. Locks: constancia ≠ cargada; no Match/persist alert; 5m cargada timer + uncheck cancel; two 5m windows; UNIQUE factura; Factura chip = cargada. Novedad **out of scope**. Guia **in scope**. No new estado, Alembic, `tipo=foto`, or GBP chip.

## Review Workload Forecast

| Field | Value |
| Estimated changed lines | 900–1400 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR1 BE → PR2 FE → PR3 Depósito ID → PR4 photo → PR5 tipo+OC+guia |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
| 1 | BE resolver+alerts+eje/tipo | PR1 tracker | `pytest tests/unit/test_recepcion_resolver_faltantes.py tests/unit/test_eje_procesal.py -q` | N/A | Phase 1 |
| 2 | FE resolver+tabs+banner | PR2←PR1 | `vitest run src/components/compras/ModalPedidoDetalle.test.jsx` | N/A | Phase 2 |
| 3 | Depósito ID | PR3←PR2 | `vitest run src/components/compras/TabRecepcionDeposito.test.jsx` | N/A | Phase 3 |
| 4 | Control #16 | PR4←PR3 | `vitest run src/components/compras/TabRecepcionDeposito.test.jsx` | N/A | Phase 4 |
| 5 | Tipo+#19+guia | PR5←PR4 | `vitest run src/components/compras/ModalPedidoCompra.test.jsx` | N/A | Phase 5 |

## Phase 1: BE 15+17

- [x] 1.1 `backend/app/schemas/recepcion.py`: `texto` required.
- [x] 1.2 `backend/app/services/recepcion_service.py`: resolver 422/409; keep `con_faltantes`; writer=responsable OR `gestionar_ordenes_compra`.
- [x] 1.3 `backend/app/routers/administracion_compras.py`: drop depósito writer; `get_current_user` (depósito-only → 403).
- [x] 1.4 `backend/app/services/compras_alertas_service.py`: `retractar_faltantes`; G31 texto + deposito deep-link query tab=deposito and pedido id; pass `codigo_producto` via `backend/app/services/notificacion_service.py`.
- [x] 1.5 `backend/app/api/endpoints/notificaciones.py`: HTTP 409 on ok, descartar, and bulk-descartar for `compras.faltantes`; snooze/factura/G31 OK stay.
- [x] 1.6 `backend/app/services/pedidos_service.py` + `backend/app/routers/administracion_compras.py`: `eje_procesal` comma-OR + `tipo`; exclude `servicio`.
- [x] 1.7 Tests in `backend/tests/unit/test_recepcion_resolver_faltantes.py`, `backend/tests/unit/test_compras_alertas_service.py`, `backend/tests/unit/test_eje_procesal.py`, `backend/tests/unit/test_notificacion_service.py`, `backend/tests/integration/test_recepcion_deposito_endpoints.py`.

## Phase 2: FE 15+17

- [ ] 2.1 `frontend/src/hooks/useRecepcionDeposito.js`: add `resolverFaltantes` POST.
- [ ] 2.2 `frontend/src/components/compras/ModalPedidoDetalle.jsx`: required textarea if `faltantes_sin_res`; hide after stamp; label “Faltantes con resolución”.
- [ ] 2.3 `frontend/src/components/AppLayout.jsx`: `compras.faltantes` not dismissible.
- [ ] 2.4 `frontend/src/components/compras/TabRecepcionDeposito.jsx`: Recibidos eje_procesal=recibido,faltantes_con_res; Con faltantes=faltantes_sin_res; expand deep-link pedido query.
- [ ] 2.5 `frontend/src/components/compras/TabPedidosCompra.jsx`: same eje label.
- [ ] 2.6 Tests in `frontend/src/components/compras/ModalPedidoDetalle.test.jsx`, `frontend/src/components/AppLayout.comprasBanners.test.jsx`, `frontend/src/components/compras/TabRecepcionDeposito.test.jsx`, `frontend/src/components/compras/TabPedidosCompra.test.jsx`.

## Phase 3: Depósito ID

- [ ] 3.1 `frontend/src/components/compras/TabRecepcionDeposito.jsx`: Cargada badge iff `factura_cargada`; `identChips` (factura + `pedidos_documento`, 60ch+title) all rows incl CON-OC.
- [ ] 3.2 `docs/modulos/compras-guia-usuario.md`: OC chip = vinculación (not GBP).
- [ ] 3.3 Tests badge + chips in `frontend/src/components/compras/TabRecepcionDeposito.test.jsx`.

## Phase 4: Control photo (#16)

- [ ] 4.1 `frontend/src/components/compras/TabRecepcionDeposito.jsx`: optional obs + `AdjuntosPanel` `tipo=otro` on control incl OK (upload-then-control).
- [ ] 4.2 Tests OK empty / OK with obs+photo in `frontend/src/components/compras/TabRecepcionDeposito.test.jsx`.

## Phase 5: Tipo + multi-OC + guia

- [ ] 5.1 `frontend/src/components/compras/ModalPedidoCompra.jsx`: create tipo selector (default `mercaderia`).
- [ ] 5.2 `frontend/src/components/compras/TabRecepcionDeposito.jsx`: Por recibir `tipo=mercaderia`.
- [ ] 5.3 `frontend/src/components/compras/TabPedidosCompra.jsx`: if ocs.length>1 show per-OC poh labels; N=1 chip only; no GBP chip.
- [ ] 5.4 `docs/modulos/compras-guia-usuario.md`: resolve/G31/Depósito/tipo/control flows.
- [ ] 5.5 Tests tipo + multi-OC in `frontend/src/components/compras/ModalPedidoCompra.test.jsx`, `frontend/src/components/compras/TabPedidosCompra.test.jsx`.
