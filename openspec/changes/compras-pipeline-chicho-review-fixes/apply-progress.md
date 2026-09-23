# Apply Progress: compras-pipeline-chicho-review-fixes

**Change**: compras-pipeline-chicho-review-fixes
**Mode**: Standard
**Batch**: Phase 4 / tasks 4.1–4.4 — PR4 #1324 (4.5 draft written, untracked, pending Gabe)
**Branch**: `feat/compras-ops-pipeline-04-multi-oc`
**Delivery**: auto-chain / feature-branch-chain
**Attempt token**: `sha256:5e656d13a7ec755fe1925a964653f7fc690e45e00584c8e0ec3ef7625b2807af`

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
- [x] 4.1 Always render one OC block; copy `OC no encontrada en ERP` if ERP empty
- [x] 4.2 TabRecepcionDeposito tests: empty-ERP block + sibling with lines
- [x] 4.3 `test_vincular_oc_multi.py`: 1-of-3 stays `recibido` or `faltantes_*`
- [x] 4.4 Document unlink-all in `docs/modulos/compras-guia-usuario.md`

## Remaining Tasks

- [ ] 4.5 **SUPERSEDED** — original draft said Match = cargada. Rewrite is task 6.3. Do not commit the old copy.
- [ ] 5.1–5.7 PR5 — stop notify-on-persist; `cargada` columns + `compras_047`; PATCH; 5-min pending-alert sweep; rewrite BE tests (row ≠ chip; timer fire/cancel).
- [ ] 6.1–6.3 PR6 — detalle checkbox; chip from `cargada`; rewrite novedad + guía; Gabe gate.

**Planning amend (2026-09-23):** Gabe correction applied to proposal/design/specs/tasks. No product code in this amend turn. Next = apply Phase 5.

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

### Phase 4 (this batch — 4.1–4.4)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/integration/test_vincular_oc_multi.py -q` → **11 passed** in 4.58s (CRLF-stripped env); `pnpm exec vitest run src/components/compras/TabRecepcionDeposito.test.jsx` → **45 passed** in 2.64s |
| Runtime harness command/scenario and exact result | N/A — no new HTTP route; empty-ERP is RTL; 1-of-3 is service-level on existing `registrar_ingresos`. Gabe gate is the novedad commit, not a runtime harness. |
| Rollback boundary | Revert TabRecepcionDeposito empty-block + CSS + two RTL cases; revert 1-of-3 test; revert guía unlink-all paragraph; revert `compras_045.down_revision` to 044. Merge of Phase 3 tip is a separate rollback. Drop untracked novedad draft if unused. |

## Deviations from Design

None — implementation matches design. Alembic rehang is 044 → 046 → 045 (`compras_045.down_revision` = `compras_046_seed_ver_alertas_factura`). `alembic heads` → single head `compras_045_pedido_compra_ocs`. 4.5 draft written and left untracked per Gabe gate.

## Issues Found

None for this slice. GGA may still fail on missing Claude CLI / pre-existing debt (Gabe authorized `--no-verify` for that class).
