# Design: Compras Pipeline Chicho Review Fixes

## Technical Approach

Close the Match write/read split and Chicho holes on #1320–#1324 (Gabe → sernafernando **main**). Reuse `agregar_factura_documento`, `seed_factura_documentos`, `resolver_usuarios_con_algun_permiso`, `max_alertas_visibles`, D-UNDO-R. No new HTTP. No admin-ocs. One novedad draft; Gabe reads before commit.

## Architecture Decisions

| ID | Option | Tradeoff | Decision |
|----|--------|----------|----------|
| D-WB-ALTA | Worker-only insert vs shared alta | Duplicate identity | After `apply_writeback`, same FOR UPDATE txn calls persist extracted from `agregar_factura_documento`. Writeback stays text-only. `created_by_id` = `pedido.creado_por_id`. Casefold-skip; then `notificar_factura_cargada`. |
| D-044 | New rev vs amend 044 | 044 not on main; some PR1 DBs applied | Amend `compras_044`: skip `len>100` (log), casefold-dedupe per pedido, `UniqueConstraint(pedido_id, numero)`. Store first-seen casing. Follow-up only if rewrite impossible. |
| D-UQ-CASE | citext / `lower()` unique vs app casefold | PG UNIQUE is case-sensitive | App casefold at seed + persist. UNIQUE on stored `numero`. Accept rare mixed-case race. |
| D-READ-SEED | List-time GET write vs migrate/writeback | GET side effects | Do **not** seed on chips/GET. Harden `seed_factura_documentos` (100 / casefold / no re-seed) for explicit backfill only. 044 + Match alta cover identity. |
| D-PERM | Keep D-FANOUT vs resolver | Titular/Admin lose auto-alerts | `destinatarios_factura` = `resolver_usuarios_con_algun_permiso(["administracion.ver_alertas_factura"])`. Drop `ROLES_FACTURA` / MarcaPM. SUPERADMIN still matches via `PermisosService`. Faltantes stay `responsable_id`. |
| D-046 | Seed on PR2 vs after 045 | 045 already on PR4 | `compras_046_seed_ver_alertas_factura` like `compras_020`: catalog only, no role grants, `orden=176`. Prefer `down_revision=compras_044` on #1322 and rehang `compras_045` → 046 on #1324. If 045 already applied, hang 046 after 045. |
| D-BANNER | Rotate compras vs cap | Rotation hides unpaid OK | Slice `comprasAlertas` to `max_alertas_visibles`. Overflow text `+N más` (not a slot). No timed rotation of compras banners. |
| D-UNDO | Change service vs tests | D-UNDO-R already correct | Tests only: double undo 409, CC+`pagado_en` → `pagado`, HTTP 403 via `require_permiso`. |
| D-ERP-UI | Hide empty vs keep block | Honest link | Always render one section per linked OC. Copy `OC no encontrada en ERP`. Keep unlink-all; document. Granular DELETE out of scope unless apply finds it cheap. |
| D-CHAIN | New PRs vs existing | Review budget | Land on #1320→#1324. PR1=D-WB-ALTA+D-044. PR2=D-PERM+D-046+D-BANNER. PR3=D-UNDO. PR4=D-ERP-UI+1-of-3+novedad (Gabe gate). |

## Data Flow

```
worker persist (SELECT FOR UPDATE)
  apply_writeback → facturas_documento token
  persist_factura_documento → row (skip casefold / >100)
       └─ notificar_factura_cargada
            └─ resolver(administracion.ver_alertas_factura)
                 └─ AppLayout: first max_alertas_visibles + "+N más"
chips / falta-factura ← rows only
```

## File Changes

| File | Action | Why |
|------|--------|-----|
| `backend/app/services/pedidos_service.py` | Modify | Extract persist; casefold-skip; harden seed |
| `backend/app/services/oc_match/worker.py` | Modify | Call persist after writeback, same txn |
| `backend/app/services/oc_match/doc_refs.py` | Keep | Text tokens only |
| `backend/app/models/pedido_factura_documento.py` | Modify | `UniqueConstraint(pedido_id, numero)` |
| `backend/alembic/versions/compras_044_pipeline_tipo_responsable_facturas.py` | Amend | 100 / dedupe / UNIQUE |
| `backend/alembic/versions/compras_046_seed_ver_alertas_factura.py` | Create | Catalog seed; hang per D-046 |
| `backend/alembic/versions/compras_045_pedido_compra_ocs.py` | Modify | Rehang `down_revision` if 046 precedes 045 |
| `backend/app/services/compras_alertas_service.py` | Modify | Resolver; drop role/PM queries |
| `frontend/src/components/AppLayout.jsx` + `.module.css` + `AppLayout.comprasBanners.test.jsx` | Modify | Cap + overflow |
| `backend/tests/unit/test_pedido_factura_documentos.py` | Modify | Overflow, casefold, UNIQUE, Match chip-on |
| `backend/tests/unit/test_compras_alertas_service.py` | Modify | Permission holders; ADMIN excluded; faltantes unchanged |
| `backend/tests/integration/test_oc_match_worker.py` | Modify | Persist creates row |
| `backend/tests/integration/test_recepcion_deposito_endpoints.py` | Modify | Three undo tests |
| `frontend/src/components/compras/TabRecepcionDeposito.jsx` + `.test.jsx` | Modify | Empty ERP block + copy |
| `backend/tests/integration/test_vincular_oc_multi.py` | Modify | 1-of-3 stays non-controlado |
| `docs/modulos/compras-guia-usuario.md` | Modify | Desvincular-all note |
| `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md` | Create | Draft only; **no commit until Gabe reviews** |

## Interfaces / Contracts

No new routes. Persist helper: skip if `numero.casefold()` exists or `len>100` (log); else insert + notify. Seed: same rules; raw `facturas_documento` unchanged. Permiso: `administracion.ver_alertas_factura`, no default roles. Banner overflow: `+{hidden} más`. Undo: service unchanged; 403 is router `deposito.recibir_mercaderia`.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Seed overflow/dedupe; persist skip; chip-on; resolver fan-out; ADMIN excluded; faltantes not permiso | pytest; rewrite alert fixtures |
| Integration | Worker row same txn; 1-of-3; undo 409 / CC+`pagado_en` / HTTP 403 | existing compras fixtures |
| Frontend | Cap 3 of 7 → `+4 más`; empty OC copy; sibling blocks | vitest + RTL |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

Amend 044 on #1320 (not main). Seed 046 per D-046. Revert stacked commits to roll back. Unassign permiso to stop factura fan-out. Downgrade 046 deletes the catalog row.

## Open Questions

- [ ] Confirm whether any PR1/PR4 DB already applied 044/045 before choosing 046 parent (apply-time, not a product block).
