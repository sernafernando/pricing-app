# Design: Compras Faltantes Responsable CAS

## Technical Approach

Approach 1 from proposal. No Alembic. Do not amend `compras-pipeline-reqs-closure`. Branch `feat/compras-faltantes-responsable-cas` from tip `feat/compras-pipeline-reqs-closure-05-tipo-oc-guia`.

1. Fence `resolver_faltantes` with SQL UPDATE (oc_match `claim_queued_job` pattern).
2. Optional `responsable_id` on mark-faltantes only; assign on ORM then existing `notificar_faltantes`.
3. Pool GET via `resolver_usuarios_con_algun_permiso`. FE selector on both Depósito mark bars.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|----------|--------|----------|-----------|
| CAS | `update(PedidoCompra).where(id, faltantes_resuelto_en IS NULL, estado=con_faltantes)`; rowcount 0 → 409; refresh | In-memory assign | Two writers can both pass Python null check |
| Assign path | Helper in `recepcion_service` on ingresos/confirmar when `nuevo_estado == con_faltantes` | Widen `_puede_editar_responsable` | PATCH still 409 on reception estados; Gabe = mark path only |
| Current not in pool | Same-as-current / omit = no perm re-check | Force pool member | Create defaults `created_by` |
| Invalid chosen | 422 | 403 | Validation, not auth |
| Control OK | Ignore `responsable_id` | 422 if sent | Avoid accidental reassign |
| Pool | `GET /administracion/compras/usuarios-responsable-faltantes` `{id,nombre}[]`; auth `deposito.recibir_mercaderia` | `GET /usuarios`, `/usuarios/pms` | Admin-only / wrong set |
| Remarcado | Allow re-pick; stack alert | Retract-and-replace | Today already stacks |
| PATCH | Unchanged | — | Admin\|creator only |

## Data Flow

```
Depósito mark faltantes
  GET pool (deposito.recibir_mercaderia)
  POST ingresos|confirmar {faltantes_texto, responsable_id?}
       │ omit/same → keep R
       │ new U → active + gestionar_ordenes_compra else 422
       ▼
  pedido.responsable_id = chosen
  notificar_faltantes → compras.faltantes to chosen

PM resolve
  texto 422 / writer 403
  UPDATE stamp WHERE id AND stamp IS NULL AND estado=con_faltantes
       │ rowcount 0 → 409 (no 2nd G31)
       ▼
  retract + G31 (unchanged)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/services/recepcion_service.py` | Modify | CAS stamp; `_asignar_responsable_en_faltantes` before alert |
| `backend/app/schemas/recepcion.py` | Modify | optional `responsable_id` on ingresos + confirmar |
| `backend/app/routers/administracion_compras.py` | Modify | pool GET |
| `frontend/src/hooks/useRecepcionDeposito.js` | Modify | send id; fetch pool |
| `frontend/src/components/compras/TabRecepcionDeposito.jsx` | Modify | selector CON-OC + SIN-OC |
| `docs/modulos/compras-guia-usuario.md` | Modify | §3.7 picker |
| `frontend/src/novedades/2026-09-23-compras-pipeline-ux.md` | Modify | Depósito picks responsable |
| `backend/app/services/pedidos_service.py` | Unchanged | `_puede_editar_responsable` stays |

## Interfaces / Contracts

```python
# RegistrarIngresosRequest / ConfirmarPedidoRequest
responsable_id: int | None = None  # applied only if nuevo_estado == "con_faltantes"

# GET /administracion/compras/usuarios-responsable-faltantes
# 200: [{id: int, nombre: str}, ...]
# 403 without deposito.recibir_mercaderia

# resolver_faltantes CAS (same session)
result = session.execute(
    update(PedidoCompra)
    .where(PedidoCompra.id == pedido.id,
           PedidoCompra.faltantes_resuelto_en.is_(None),
           PedidoCompra.estado == "con_faltantes")
    .values(faltantes_resuelto_en=stamp)
)
if int(result.rowcount or 0) == 0:
    raise HTTPException(409, "Los faltantes ya fueron resueltos.")
session.refresh(pedido)
```

Keep texto 422 + writer 403 **before** UPDATE. After win: event, retract, G31 (unchanged).

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | CAS rowcount 0 → 409, no 2nd G31; assign/omit/same/invalid; ignore on controlado | `test_recepcion_resolver_faltantes.py`; ingresos/confirmar units |
| Unit | Alert to chosen | `test_compras_alertas_service.py` after assign |
| Integration | Resolver 409 re-resolve; ingresos/confirmar + pool 403 | `test_recepcion_deposito_endpoints.py` |
| FE | Picker default + send id on mark only | `TabRecepcionDeposito.test.jsx` |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration required. New branch from the tip; PR to `develop`.

## Open Questions

None.
