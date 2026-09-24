# Apply Progress: compras-pipeline-chicho-review-fixes

**Change**: compras-pipeline-chicho-review-fixes
**Mode**: Standard
**Batch**: Phase 6 / tasks 6.1–6.2 — PR6 FE checkbox + chip (6.3 novedad draft pending Gabe)
**Branch**: `feat/compras-ops-pipeline-04-multi-oc`
**Delivery**: auto-chain / feature-branch-chain
**Attempt token**: `sha256:f591a64fa57a2ee810eb48e0b4847f0f03be1b2ef5275e499c830623cb217596`

## Completed Tasks

- [x] 1.1 Extract `persist_factura_documento` from `agregar_factura_documento` (skip `len>100` + log, casefold-dupe, insert)
- [x] 1.2 Harden `seed_factura_documentos` (100 / casefold / no re-seed). Chips/GET/list do not call seed
- [x] 1.3 Worker calls persist after `apply_writeback` in the same FOR UPDATE txn with `created_by_id=pedido.creado_por_id`
- [x] 1.4 `UniqueConstraint(pedido_id, numero)` on `PedidoFacturaDocumento`
- [x] 1.5 Amend `compras_044`: skip overflow (log), casefold-dedupe, UNIQUE, first-seen casing
- [x] 1.6 Unit + integration tests for overflow/casefold/UNIQUE, Match persist
- [x] 2.1 `compras_046_seed_ver_alertas_factura` catalog seed; no roles; `orden=176`
- [x] 2.2 `destinatarios_factura` via `resolver_usuarios_con_algun_permiso`; drop `ROLES_FACTURA`/MarcaPM
- [x] 2.3 Alertas unit tests: holders only; ADMIN without code out; SUPERADMIN via resolver; faltantes unchanged
- [x] 2.4 Cap `comprasAlertas` to `max_alertas_visibles`; overflow `+N más`; no compras timed-rotate
- [x] 2.5 AppLayout banners: 7/cap 3 → 3 + `+4 más`; unread stays until OK
- [x] 3.1 Undo tests only: second undo HTTP 409; CC+`pagado_en` → `pagado`; HTTP 403 via `require_permiso("deposito.recibir_mercaderia")`
- [x] 4.1 Always render one OC block; copy `OC no encontrada en ERP` if ERP empty
- [x] 4.2 TabRecepcionDeposito tests: empty-ERP block + sibling with lines
- [x] 4.3 `test_vincular_oc_multi.py`: 1-of-3 stays `recibido` or `faltantes_*`
- [x] 4.4 Document unlink-all in `docs/modulos/compras-guia-usuario.md`
- [x] 5.1 Cargada columns on `PedidoFacturaDocumento` (default false, no backfill)
- [x] 5.2 `compras_047_factura_cargada_erp` parent `compras_045`; pending index
- [x] 5.3 Persist/Match/alta no notify; chip = `cargada=true`; `marcar_factura_cargada`
- [x] 5.4 Sweep `disparar_alertas_factura_pendientes`; uncheck cancels pending
- [x] 5.5 Cron `dispatch_factura_cargada_alerts.py` (no BackgroundTasks.sleep)
- [x] 5.6 PATCH `pedidos/{id}/factura-documentos/{row_id}`; detalle rows + flags
- [x] 5.7 BE tests rewritten: row ≠ cargada; timer fire/cancel; Match chip-off
- [x] 6.1 Detalle lists `factura_documentos` as constancia + ERP checkbox; PATCH `{cargada}`; blob is not cargada; NV/`pedidos_documento` text-only
- [x] 6.2 List + detalle “Factura” chip from `factura_cargada`; muted “Número” when `tiene_numero_factura` and not cargada; chip-off-with-numbers + chip-on-after-check

## Remaining Tasks

- [ ] 4.5 **SUPERSEDED** — original draft said Match = cargada. Rewrite is task 6.3. Do not commit the old copy.
- [ ] 6.3 **GATE** — novedad rewritten on disk (untracked). Guía updated and committed with 6.1–6.2. **Do not mark complete until Gabe OKs the novedad.** Show Gabe the draft at `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md`.

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

### Phase 3 (prior batch)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/integration/test_recepcion_deposito_endpoints.py -k undo -q` → **6 passed**, 96 deselected in 3.60s (CRLF-stripped env) |
| Runtime harness command/scenario and exact result | N/A — D-UNDO-R already live; HTTP 409/403 covered by TestClient against `POST /pedidos/{id}/recepcion/deshacer-recibido`. No new production path. |
| Rollback boundary | Revert the three new methods on `TestDeshacerRecibido` plus this SDD checkbox/progress. Merge of `aa319c04` into this branch is a separate rollback (revert merge commit). |

### Phase 4 (prior batch — 4.1–4.4)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/integration/test_vincular_oc_multi.py -q` → **11 passed** in 4.58s (CRLF-stripped env); `pnpm exec vitest run src/components/compras/TabRecepcionDeposito.test.jsx` → **45 passed** in 2.64s |
| Runtime harness command/scenario and exact result | N/A — no new HTTP route; empty-ERP is RTL; 1-of-3 is service-level on existing `registrar_ingresos`. Gabe gate is the novedad commit, not a runtime harness. |
| Rollback boundary | Revert TabRecepcionDeposito empty-block + CSS + two RTL cases; revert 1-of-3 test; revert guía unlink-all paragraph; revert `compras_045.down_revision` to 044. Merge of Phase 3 tip is a separate rollback (revert merge commit). Drop untracked novedad draft if unused. |

### Phase 5 (prior batch — 5.1–5.7)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/unit/test_pedido_factura_documentos.py tests/unit/test_compras_alertas_service.py tests/integration/test_oc_match_worker.py tests/unit/test_eje_procesal.py -q` → **79 passed** in 43.75s (CRLF-stripped env, admin-ocs venv) |
| Runtime harness command/scenario and exact result | N/A — PATCH/DELETE covered by FastAPI TestClient on the same SQLite session; sweep uses injectable `ahora`. No BackgroundTasks.sleep. Cron script is a thin `SessionLocal` wrapper around the sweep. |
| Rollback boundary | Revert `compras_047` + model cols + persist notify removal + chip query + `marcar_factura_cargada` + sweep + cron + PATCH/schemas + the three rewritten test files + `test_eje_procesal` cargada flag. Leave novedad untracked. |

### Phase 6 (this batch — 6.1–6.2; 6.3 draft only)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pnpm exec vitest run src/components/compras/ModalPedidoDetalle.test.jsx src/components/compras/TabPedidosCompra.test.jsx` → **5 passed** in 2.57s |
| Runtime harness command/scenario and exact result | N/A — RTL + mocked axios; PATCH path is `api.patch(/administracion/compras/pedidos/{id}/factura-documentos/{row_id}, {cargada})`. 6.3 is a Gabe copy gate, not a runtime harness. |
| Rollback boundary | Revert ModalPedidoDetalle checkbox/PATCH + TabPedidosCompra muted Número + the two new test files + guía constancia/cargada paragraphs + SDD 6.1–6.2 checkboxes. Leave novedad untracked. |

## Deviations from Design

None — implementation matches design. Guía shipped with 6.1–6.2 (same semantics) so operators are not left on the old “row = cargada” copy; novedad stays untracked until Gabe reviews (task 6.3).

## Issues Found

None for 6.1–6.2. Task 6.3 is **draft ready pending Gabe** — do not settle 6.3 complete and do not commit the novedad until he OKs.
