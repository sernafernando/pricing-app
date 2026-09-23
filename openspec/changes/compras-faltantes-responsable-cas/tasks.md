# Tasks: Compras Faltantes Responsable CAS

Stack branch `feat/compras-faltantes-responsable-cas` on tip `feat/compras-pipeline-reqs-closure-05-tipo-oc-guia`. Do not amend `compras-pipeline-reqs-closure`. No Alembic. Current responsable always valid.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 220–360 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | CAS + assign + pool + FE + docs | single | `pytest tests/unit/test_recepcion_resolver_faltantes.py tests/integration/test_recepcion_deposito_endpoints.py::TestResolverFaltantesHttp -q` + `pnpm exec vitest run --project=unit src/components/compras/TabRecepcionDeposito.test.jsx` | N/A — operator picker + resolve race covered by unit/integration | Revert branch; no Alembic |

## Phase 1: CAS + tests

- [x] 1.1 RED in `backend/tests/unit/test_recepcion_resolver_faltantes.py`: rowcount 0 → 409; no second G31 (`Resolve faltantes stamps at most once`).
- [x] 1.2 GREEN `backend/app/services/recepcion_service.py`: `update(PedidoCompra)` WHERE stamp IS NULL AND `estado=con_faltantes`; refresh; keep texto 422 + writer 403 before UPDATE.

## Phase 2: Mark-path assign + pool

- [x] 2.1 `backend/app/schemas/recepcion.py`: optional `responsable_id` on ingresos + confirmar.
- [x] 2.2 `backend/app/services/recepcion_service.py`: assign only if `nuevo_estado == con_faltantes`; omit/same keep current; else active + `gestionar_ordenes_compra` or 422; then `notificar_faltantes`.
- [x] 2.3 `backend/app/routers/administracion_compras.py`: `GET /usuarios-responsable-faltantes` via `resolver_usuarios_con_algun_permiso`; auth `deposito.recibir_mercaderia`.
- [x] 2.4 Tests assign/omit/invalid/control-ignore + pool 403 in `backend/tests/integration/test_recepcion_deposito_endpoints.py` and `backend/tests/unit/test_compras_alertas_service.py` (chosen gets alert). Leave `backend/app/services/pedidos_service.py` unchanged.

## Phase 3: FE selector

- [x] 3.1 `frontend/src/hooks/useRecepcionDeposito.js`: fetch pool; send `responsable_id` on mark only.
- [x] 3.2 `frontend/src/components/compras/TabRecepcionDeposito.jsx`: selector on CON-OC + SIN-OC mark bars; default current ∪ pool.
- [x] 3.3 Tests default + payload in `frontend/src/components/compras/TabRecepcionDeposito.test.jsx`.

## Phase 4: Docs

- [x] 4.1 `docs/modulos/compras-guia-usuario.md` §3.7: Depósito picks responsable.
- [x] 4.2 `frontend/src/novedades/2026-09-23-compras-pipeline-ux.md`: same picker sentence.
