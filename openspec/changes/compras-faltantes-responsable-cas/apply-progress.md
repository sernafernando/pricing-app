# Apply Progress: compras-faltantes-responsable-cas

Mode: Standard (not Strict TDD)
Branch: `feat/compras-faltantes-responsable-cas` (from tip `feat/compras-pipeline-reqs-closure-05-tipo-oc-guia` @ acfe81af)
Delivery: single PR (forecast Decision needed: No). Authored source+tests+docs **557** (548+/9−) before SDD artifact write — over the 400 review budget and the 500 acquire cap. Honest size:exception; do not shrink tests/docs.

## Work Unit Evidence (cas-assign-pool-fe)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `ENVIRONMENT=testing pytest tests/unit/test_recepcion_resolver_faltantes.py tests/unit/test_compras_alertas_service.py tests/integration/test_recepcion_deposito_endpoints.py::TestResolverFaltantesHttp tests/integration/test_recepcion_deposito_endpoints.py::TestResponsableFaltantesAssignAndPool -q` → **39 passed**. `pnpm exec vitest run --project=unit src/components/compras/TabRecepcionDeposito.test.jsx` → **61 passed**. eslint on touched FE: pass. ruff format on touched Python: pass. |
| Runtime harness command/scenario and exact result | N/A — design threat matrix is N/A; no new routing/shell/process boundary. CAS race, mark-path assign, pool 403, and picker payload are covered by pytest TestClient + jsdom vitest. |
| Rollback boundary | Revert this branch. Restores in-memory stamp (no CAS fence), no mark-path `responsable_id`, no pool GET, no Depósito picker. No Alembic. `pedidos_service._puede_editar_responsable` untouched. |

## Completed Tasks

### Phase 1 — CAS
- [x] 1.1 `test_cas_lost_race_409_no_second_g31`: DB already stamped + stale ORM None → 409; G31/retract not called
- [x] 1.2 `resolver_faltantes`: `update(PedidoCompra)` WHERE stamp IS NULL AND `estado=con_faltantes`; rowcount 0 → 409; refresh then keep tz-aware stamp; texto 422 + writer 403 stay before UPDATE

### Phase 2 — Assign + pool
- [x] 2.1 optional `responsable_id` on `RegistrarIngresosRequest` + `ConfirmarPedidoRequest`
- [x] 2.2 `_asignar_responsable_en_faltantes` only when `nuevo_estado == con_faltantes`; omit/same keep current; else active + `gestionar_ordenes_compra` or 422; then `notificar_faltantes`
- [x] 2.3 `GET /administracion/compras/usuarios-responsable-faltantes` via `resolver_usuarios_con_algun_permiso`; auth `deposito.recibir_mercaderia`
- [x] 2.4 assign/omit/same/invalid/control-ignore + pool 403/200; chosen gets `compras.faltantes`. `pedidos_service.py` unchanged

### Phase 3 — FE
- [x] 3.1 hook fetches pool; sends `responsable_id` on mark only
- [x] 3.2 selector on CON-OC + SIN-OC mark bars; options = current ∪ pool
- [x] 3.3 vitest: default current (even outside pool); mark payload includes id; control complete does not send id

### Phase 4 — Docs
- [x] 4.1 guía §3.7: Depósito picks responsable
- [x] 4.2 novedad: same picker sentence

## Deviations from Design
None — implementation matches design. After a winning CAS UPDATE, the service refreshes then writes the in-memory `stamp` so SQLite naive datetimes do not leak to the response.

## Issues Found
None blocking. Authored line count exceeded the 400/500 caps because assign+pool+CAS+FE+tests+docs are one locked work unit.

## Remaining Tasks
None — 11/11 complete.

## Attempt settle
`gentle-ai sdd-attempt settle` with token `sha256:07b41d4c…` returned `blocked` / `maintainer_decision` because authored lines (557) exceed `--max-changed-lines 500`. Tests passed. Needs maintainer reset or accepted size:exception before the runtime marks the attempt passed.

## Workload / PR Boundary
- Mode: single PR with size:exception (557 authored lines)
- Current work unit: cas-assign-pool-fe
- Boundary: CAS resolve + mark-path responsable + pool GET + Depósito picker + docs
- Estimated review budget impact: over 400; keep as one PR — splitting would leave FE without BE or CAS without assign
