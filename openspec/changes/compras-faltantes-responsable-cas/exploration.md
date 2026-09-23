# Exploration: compras-faltantes-responsable-cas

Gabe locked: CAS on `resolver_faltantes`; Depósito picker of `responsable` when marking faltantes (default=current, pool=`administracion.gestionar_ordenes_compra`, BE validates, alert to chosen). New change stacked on tip `feat/compras-pipeline-reqs-closure-05-tipo-oc-guia`. Do **not** amend `compras-pipeline-reqs-closure`.

English technical artifact. No production code.

---

## Current State

### Resolver (no CAS)

`recepcion_service.resolver_faltantes` checks `estado == con_faltantes` and `faltantes_resuelto_en is not None` in Python, then assigns `pedido.faltantes_resuelto_en = stamp`. Two concurrent writers can both pass the null check and both emit retract + G31. Existing `test_reresolve_409` only covers a pre-stamped row, not a lost UPDATE fence.

oc_match already has the pattern: `claim_queued_job` / worker `_persist` do `update(...).where(...)` and `if int(result.rowcount or 0) == 0: …`. Resolve should use the same fence: `UPDATE … WHERE faltantes_resuelto_en IS NULL` → rowcount 0 → HTTP 409.

### Mark faltantes (no picker)

CON-OC `POST …/recepcion/ingresos` (`RegistrarIngresosRequest`) and SIN-OC `POST …/recepcion/confirmar-pedido` (`ConfirmarPedidoRequest`) accept `faltantes_texto` (+ optional `observaciones`). Neither accepts `responsable_id`. When `nuevo_estado == "con_faltantes"`, `_alertar_faltantes_si_corresponde` → `notificar_faltantes` fans a single `compras.faltantes` to **current** `pedido.responsable_id` (empty texto 422; null responsable → no alert).

`TabRecepcionDeposito` has two mark UIs (`AccordionBodyConOc` / `AccordionBodySinOc`) with required faltantes texto and no responsable control. List DTO already carries `responsable_id`. SIN-OC shows “Con faltantes” only from `recibido`; CON-OC can remarcado while already `con_faltantes` (re-alerts today; prior rows stay until resolve).

### Responsable editors today

`_puede_editar_responsable` = admin role **or** `creado_por_id`. Spec `pedidos-compra` / Pedido responsable matches that. `editar_pedido` then 409s unless estado ∈ {borrador, aprobado, pagado_parcial, pagado} — so once the pedido is `recibido` / `con_faltantes`, **nobody** can PATCH `responsable_id`. Widening the helper would not help depósito on the reception path.

Create still defaults `responsable_id` to `created_by`. FE Pedidos/Detalle has **no** responsable picker today.

### Pool helpers

`resolver_usuarios_con_algun_permiso` (hybrid role+overrides; SUPERADMIN always matches) is the correct pool source. `GET /usuarios` is ADMIN/SUPERADMIN only. `GET /usuarios/pms` returns all active users (or MarcaPM) — wrong pool, do not reuse.

---

## Affected Areas

- `backend/app/services/recepcion_service.py` — CAS stamp; assign `responsable_id` on mark-faltantes before alert
- `backend/app/schemas/recepcion.py` — optional `responsable_id` on ingresos + confirmar
- `backend/app/services/pedidos_service.py` — leave `_puede_editar_responsable` unchanged (admin|creator only)
- `backend/app/services/compras_alertas_service.py` — no recipient rewrite if assign happens first; still `pedido.responsable_id`
- `backend/app/services/notificacion_service.py` — reuse `resolver_usuarios_con_algun_permiso` for pool GET
- `backend/app/routers/administracion_compras.py` — small pool endpoint + resolver 409 on lost CAS
- `frontend/src/components/compras/TabRecepcionDeposito.jsx` — selector on both mark-faltantes bars
- `frontend/src/hooks/useRecepcionDeposito.js` — send `responsable_id`; fetch pool
- `frontend/src/services/api.js` — pool client if not folded into the hook
- Tests: `test_recepcion_resolver_faltantes.py` (CAS rowcount 0), recepcion ingresos/confirmar (assign + 422 invalid), `test_compras_alertas_service.py` (alert to chosen), `TabRecepcionDeposito.test.jsx`
- Docs: `docs/modulos/compras-guia-usuario.md` §3.7 (Depósito picks who gets the PM alert)
- Delta specs later (this change’s `specs/`, not reqs-closure): `pedidos-compra`, `recepcion-deposito`, `recepcion-estados`, `compras-pipeline-alerts`

Do **not** edit `openspec/changes/compras-pipeline-reqs-closure/`.

---

## Approaches

1. **Mark-path assign + CAS stamp (recommended)** — Optional `responsable_id` only on ingresos/confirmar when transitioning/staying `con_faltantes`. Default omit = current. Chosen user MUST be active and hold `administracion.gestionar_ordenes_compra` (unless id equals current). Set on the ORM row, then existing `notificar_faltantes`. New GET pool via `resolver_usuarios_con_algun_permiso`. Resolver uses `update(PedidoCompra).where(id, faltantes_resuelto_en IS NULL [, estado=con_faltantes]).values(stamp)`; rowcount 0 → 409; refresh ORM. Do not change PATCH editors.
   - Pros: Matches Gabe; no Alembic; reuses alert + permission resolver; PATCH law stays; race-safe stamp
   - Cons: Extra tiny GET; remarcado CON-OC can re-pick (same as today’s re-alert)
   - Effort: Medium

2. **Widen `_puede_editar_responsable` to depósito + PATCH** — Let depósito PATCH any time.
   - Pros: One helper
   - Cons: Breaks admin|creator spec as a general rule; PATCH still 409 on reception estados; depósito could reassign outside faltantes; over-scope
   - Effort: Medium — **reject**

3. **CAS-only, no picker** — Fence resolve; keep alert to whatever `responsable_id` already is.
   - Pros: Tiny
   - Cons: Misses Gabe’s required picker
   - Effort: Low — **reject as sole fix**

4. **Reuse `GET /usuarios/pms` and filter in FE** — Client-side “PM list”.
   - Pros: No new endpoint
   - Cons: Pool ≠ MarcaPM / all users; depósito cannot see hybrid `gestionar_ordenes_compra`; BE would still need the same validation
   - Effort: Low — **reject**

---

## Recommendation

Ship **Approach 1** as a **new change** on tip `feat/compras-pipeline-reqs-closure-05-tipo-oc-guia` (new branch `feat/compras-faltantes-responsable-cas`). Do not amend reqs-closure.

**Locked defaults for propose (not blocking):**

1. **CAS** — `UPDATE pedidos_compra SET faltantes_resuelto_en = :stamp WHERE id = :id AND faltantes_resuelto_en IS NULL`. Also AND `estado = 'con_faltantes'` so a lost race vs controlado/wrong-estado stays 409 (same as today). `int(result.rowcount or 0) == 0` → 409. Keep texto 422 and writer 403 **before** the UPDATE. Expire/refresh the loaded `pedido` after a win. Pattern: `oc_match/enqueue.py` `claim_queued_job` / worker `_persist`.
2. **Mark path only** — `responsable_id: int | None` on `RegistrarIngresosRequest` and `ConfirmarPedidoRequest`. Apply **only** when `nuevo_estado == "con_faltantes"`. Ignore on controlado / `completo=true`. Omit or same-as-current → no write, no perm re-check.
3. **Validate chosen** — Active user + `PermisosService.tiene_permiso(..., "administracion.gestionar_ordenes_compra")`. Else 422. Then `notificar_faltantes` (unchanged) hits the new `responsable_id`.
4. **Pool GET** — e.g. `GET /administracion/compras/usuarios-responsable-faltantes` → `{id, nombre}[]` from `resolver_usuarios_con_algun_permiso([gestionar_ordenes_compra])`. Auth: `deposito.recibir_mercaderia` (markers). Do not open `GET /usuarios` to depósito.
5. **FE** — Select next to faltantes texto on CON-OC and SIN-OC mark bars. Default `pedido.responsable_id`. Options = current ∪ pool (current stays listed even if they lost the permission).
6. **Spec delta** — MODIFY `Pedido responsable`: general editors stay admin|creator; **add** faltantes-mark exception for depósito. ADD CAS + picker requirements on `recepcion-estados` / `recepcion-deposito`. Alerts stay “to `responsable_id`” after optional assign.
7. **Delivery** — Single PR if kept tight; else BE (CAS + assign + pool + tests) then FE. Target `develop`. Forecast ~200–350 authored lines (Medium budget risk if tests+docs land together).

---

## Risks

- **TOCTOU without CAS:** in-memory stamp check is not a fence; two resolves can double-retract/double-G31.
- **Current not in pool:** create defaults `created_by`, who may lack `gestionar_ordenes_compra`. Default “current always allowed; pool is for switching.” Re-sending current id must not 422.
- **Remarcado CON-OC:** second mark can change responsable and stacks another `compras.faltantes` (today already stacks to the same user). Prior rows retract only on resolve. Accept unless Gabe wants retract-and-replace.
- **PATCH footgun:** do not widen `_puede_editar_responsable`; reception estados already 409 on `editar_pedido`.
- **Pool GET cost:** resolver walks all active users (existing helper). Fine for a once-per-open picker; do not call per keystroke.
- **Ignore `responsable_id` on control OK:** sending it on `completo=true` must not reassign.

---

## Open questions

None blocking. Defaults above are enough to propose.

Non-blocking (already defaulted): current-not-in-pool stays valid; remarcado may re-pick; ignore assign on controlado; new branch from the tip (do not keep committing on the verified closure branch).

---

## Ready for Proposal

**Yes.** Orchestrator should run `sdd-propose` for `compras-faltantes-responsable-cas` with Approach 1 and the locked defaults. Next artifact: `proposal.md` (then deltas for `pedidos-compra`, `recepcion-deposito`, `recepcion-estados`, `compras-pipeline-alerts`).
