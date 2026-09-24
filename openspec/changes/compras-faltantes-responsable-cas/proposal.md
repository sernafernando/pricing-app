# Proposal: Compras Faltantes Responsable CAS

## Intent

Depósito MUST choose who owns a faltantes alert (default = current `responsable_id`). Concurrent resolve MUST NOT double-stamp. Do not amend `compras-pipeline-reqs-closure`.

## Scope

### In Scope
- CAS on `resolver_faltantes`: `UPDATE … WHERE faltantes_resuelto_en IS NULL AND estado=con_faltantes`; rowcount 0 → 409
- Optional `responsable_id` on ingresos + confirmar only when `nuevo_estado == con_faltantes`
- BE: chosen MUST be active + hold `administracion.gestionar_ordenes_compra` (current id always allowed)
- Pool GET via `resolver_usuarios_con_algun_permiso`; auth `deposito.recibir_mercaderia`
- FE selector on both Depósito mark bars; options = current ∪ pool
- Alert still `notificar_faltantes` after assign
- Guia §3.7 picker note

### Out of Scope
Amend reqs-closure; widen `_puede_editar_responsable` / PATCH; Alembic; reuse `GET /usuarios` or `/usuarios/pms`; retract-and-replace on remarcado; factura/G31/eje/tipo slices; email/Slack.

## Capabilities

### New Capabilities
None

### Modified Capabilities
- `pedidos-compra`: Pedido responsable — PATCH editors stay admin|creator; add faltantes-mark exception
- `recepcion-deposito`: picker + pool GET on mark-faltantes
- `recepcion-estados`: CAS fence on resolve
- `compras-pipeline-alerts`: alert still to `responsable_id` after optional assign

## Approach

Explore Approach 1. Set ORM `responsable_id` on mark-faltantes, then existing alert. Omit / same-as-current = no write. Ignore field on controlado. Resolver: texto 422 + writer 403, then `update(PedidoCompra)` like `claim_queued_job`; refresh on win. Branch `feat/compras-faltantes-responsable-cas` from the tip. Target `develop`. Single PR if tight; else BE then FE.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/services/recepcion_service.py` | Modified | CAS stamp; assign before alert |
| `backend/app/schemas/recepcion.py` | Modified | optional `responsable_id` |
| `backend/app/routers/administracion_compras.py` | Modified | pool GET; CAS 409 |
| `frontend/src/components/compras/TabRecepcionDeposito.jsx` | Modified | selector both mark bars |
| `frontend/src/hooks/useRecepcionDeposito.js` | Modified | send id + fetch pool |
| `backend/app/services/pedidos_service.py` | Unchanged | `_puede_editar_responsable` stays |
| `docs/modulos/compras-guia-usuario.md` | Modified | §3.7 picker |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Double resolve without CAS | High | rowcount fence |
| Current not in pool | Med | current always valid |
| Remarcado stacks alerts | Low | accept (today already stacks) |
| `responsable_id` on control OK | Med | ignore unless `con_faltantes` |

## Rollback Plan

Revert the PR/branch. No Alembic. Restores in-memory stamp, no picker, alert to pre-existing `responsable_id`.

## Dependencies

Tip `feat/compras-pipeline-reqs-closure-05-tipo-oc-guia`. Reuse `notificar_faltantes`, `resolver_usuarios_con_algun_permiso`, oc_match CAS.

## Success Criteria

- [ ] Lost CAS (rowcount 0) → 409; no second stamp/G31
- [ ] Depósito can pick a pool member on mark; default current; invalid → 422
- [ ] Alert goes to chosen; omit keeps current
- [ ] PATCH responsable still admin|creator; reception estados still 409
- [ ] reqs-closure not amended; no chicho/factura/G31 regression
