# Apply Progress: compras-pipeline-chicho-review-fixes

**Change**: compras-pipeline-chicho-review-fixes
**Mode**: Standard
**Batch**: Phase 1 / tasks 1.1–1.6 — PR1 #1320
**Branch**: `feature/compras-ux`
**Delivery**: auto-chain / feature-branch-chain
**Attempt token**: `sha256:13b6625e5cca3fb2017278990fc7c5d9971e19594a30362d9085a2e55cdcc376`

## Completed Tasks

- [x] 1.1 Extract `persist_factura_documento` from `agregar_factura_documento` (skip `len>100` + log, casefold-dupe, insert + notify hook)
- [x] 1.2 Harden `seed_factura_documentos` (100 / casefold / no re-seed). Chips/GET/list do not call seed
- [x] 1.3 Worker calls persist after `apply_writeback` in the same FOR UPDATE txn with `created_by_id=pedido.creado_por_id`
- [x] 1.4 `UniqueConstraint(pedido_id, numero)` on `PedidoFacturaDocumento`
- [x] 1.5 Amend `compras_044`: skip overflow (log), casefold-dedupe, UNIQUE, first-seen casing
- [x] 1.6 Unit + integration tests for overflow/casefold/UNIQUE, Match `FA-10` chip-on, no falta-factura

## Remaining Tasks

- [ ] 2.1–2.5 PR2 #1322 permiso + banners
- [ ] 3.1 PR3 #1323 undo tests
- [ ] 4.1–4.5 PR4 #1324 ERP UI + 1-of-3 + novedad GATE

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/unit/test_pedido_factura_documentos.py tests/integration/test_oc_match_worker.py -q` → **41 passed** in 10.81s |
| Runtime harness command/scenario and exact result | N/A — no HTTP/runtime boundary beyond pytest txn; worker path covered by integration tests on the same SQLite session as `_persist` |
| Rollback boundary | Revert persist helper + worker call + `UniqueConstraint` + `compras_044` seed/UNIQUE amend + the two test files’ new cases |

## Deviations from Design

None — persist after `apply_writeback` (writeback stays text-only); notify is a lazy hook (`compras_alertas_service` is PR2); no GET seed.

## Issues Found

None blocking. PR1 DBs that already applied 044 still lack UNIQUE until a follow-up rewrite (design D-044).
