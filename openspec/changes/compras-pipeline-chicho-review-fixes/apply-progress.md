# Apply Progress: compras-pipeline-chicho-review-fixes

**Change**: compras-pipeline-chicho-review-fixes
**Mode**: Standard
**Batch**: Phase 3 / task 3.1 — PR3 #1323
**Branch**: `feat/compras-ops-pipeline-03-deposito`
**Delivery**: auto-chain / feature-branch-chain
**Attempt token**: `sha256:fcec47addcd660d8e2a7048832477cc9fec93a1572b9dbc1d62ca41fa0b8f907`

## Completed Tasks

- [x] 1.1 Extract `persist_factura_documento` from `agregar_factura_documento` (skip `len>100` + log, casefold-dupe, insert + notify hook)
- [x] 1.2 Harden `seed_factura_documentos` (100 / casefold / no re-seed). Chips/GET/list do not call seed
- [x] 1.3 Worker calls persist after `apply_writeback` in the same FOR UPDATE txn with `created_by_id=pedido.creado_por_id`
- [x] 1.4 `UniqueConstraint(pedido_id, numero)` on `PedidoFacturaDocumento`
- [x] 1.5 Amend `compras_044`: skip overflow (log), casefold-dedupe, UNIQUE, first-seen casing
- [x] 1.6 Unit + integration tests for overflow/casefold/UNIQUE, Match `FA-10` chip-on, no falta-factura
- [x] 2.1 `compras_046_seed_ver_alertas_factura` catalog seed; no roles; `orden=176`
- [x] 2.2 `destinatarios_factura` via `resolver_usuarios_con_algun_permiso`; drop `ROLES_FACTURA`/MarcaPM
- [x] 2.3 Alertas unit tests: holders only; ADMIN without code out; SUPERADMIN via resolver; faltantes unchanged
- [x] 2.4 Cap `comprasAlertas` to `max_alertas_visibles`; overflow `+N más`; no compras timed-rotate
- [x] 2.5 AppLayout banners: 7/cap 3 → 3 + `+4 más`; unread stays until OK
- [x] 3.1 Undo tests only: second undo HTTP 409; CC+`pagado_en` → `pagado`; HTTP 403 via `require_permiso("deposito.recibir_mercaderia")`

## Remaining Tasks

- [ ] 4.1–4.5 PR4 #1324 ERP UI + 1-of-3 + novedad GATE

## Work Unit Evidence

### Phase 1 (prior batch)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/unit/test_pedido_factura_documentos.py tests/integration/test_oc_match_worker.py -q` → **41 passed** in 10.81s |
| Runtime harness command/scenario and exact result | N/A — no HTTP/runtime boundary beyond pytest txn; worker path covered by integration tests on the same SQLite session as `_persist` |
| Rollback boundary | Revert persist helper + worker call + `UniqueConstraint` + `compras_044` seed/UNIQUE amend + the two test files’ new cases |

### Phase 2 (prior batch)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/unit/test_compras_alertas_service.py -q` → **13 passed**; `pnpm exec vitest run src/components/AppLayout.comprasBanners.test.jsx` → **3 passed** |
| Runtime harness command/scenario and exact result | N/A — unit/RTL only; no new HTTP route; fan-out is resolver + persist hook already covered by pytest |
| Rollback boundary | Revert `compras_046` + `destinatarios_factura` resolver + AppLayout cap/`+N más` + the two test files’ new cases. Merge of `ff83f305` into this branch is a separate rollback (revert merge commit). |

### Phase 3 (this batch)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/integration/test_recepcion_deposito_endpoints.py -k undo -q` → **6 passed**, 96 deselected in 3.60s (CRLF-stripped env) |
| Runtime harness command/scenario and exact result | N/A — D-UNDO-R already live; HTTP 409/403 covered by TestClient against `POST /pedidos/{id}/recepcion/deshacer-recibido`. No new production path. |
| Rollback boundary | Revert the three new methods on `TestDeshacerRecibido` plus this SDD checkbox/progress. Merge of `aa319c04` into this branch is a separate rollback (revert merge commit). |

## Deviations from Design

046 parents `compras_044_pipeline_tipo_responsable_facturas` (D-046 / apply-time). `compras_045` is not on this PR3 branch; PR4 must rehang 045 → 046. Persist notify stays the lazy ImportError hook from Phase 1. Service `deshacer_recibido` unchanged (D-UNDO-R).

## Issues Found

None for this slice. GGA may still flag pre-existing N+1 / soft god-component on merged Phase 1 `pedidos_service.py` (Gabe authorized `--no-verify` for that class of FAIL only).
