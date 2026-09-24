## Exploration: compras-pipeline-chicho-review-fixes

### Amendment (Gabe 2026-09-23)

The write/read-split exploration below treated “row exists = factura cargada + alert on persist”. **That product model is wrong.** Gabe: numbers = constancia (no alert); cargada = Administración ERP check + 5-min pending alert (uncheck cancels). admin-ocs coord: Match stays Text write-back; typed rows + check live in compras-ux. Two 5-min clocks: DELETE undo (`created_at`) ≠ alert timer (`cargada_marked_at`). See proposal/design/specs/tasks as amended. Do not treat the “Shared alta fires alerts from OC Match — intended” risk below as current.

---

Chicho review of stacked PRs #1320→#1324 (Gabe fork → sernafernando **main**). Prior change `compras-ops-pipeline-ux` is archived. User locked full fix scope + one Novedades draft (Gabe gate before commit). admin-ocs confirmed catalog = DB; seed owned here; no admin-ocs code.

### Current State

**Write/read split (root bug).** OC Match `apply_writeback` (`backend/app/services/oc_match/doc_refs.py`) only mutates `pedidos_compra.facturas_documento` (append-unique `; ` tokens). Worker persist (`worker.py` ~241) does that inside `SELECT FOR UPDATE` and never touches `pedido_factura_documentos`. Chips (`es_factura_cargada` / `chips_visibilidad_batch`) and factura alerts read **rows only**. Result: Match writes a token, chip stays off, operators see a false “factura no cargada”. Manual alta (`agregar_factura_documento`) already inserts a row + fans out alerts.

**Seed `compras_044`.** `numero` is `String(100)`. Seed splits `;` and inserts raw tokens — no truncate, no dedupe, no UNIQUE. Duplicate `(pedido_id, numero)` and tokens >100 can fail or silently overflow. Service `seed_factura_documentos` exists for empty tables but is not a list read-path.

**Factura recipients.** Archived spec/design D-FANOUT = titular ∪ sub-PM ∪ `ADMIN`/`GERENTE`/`SUPERADMIN` (`ROLES_FACTURA` + `MarcaPM`/`MarcaSubPM` in `destinatarios_factura`). Chicho + admin-ocs + user lock: **`administracion.ver_alertas_factura`**, not `compras.*`. Catalog is DB `permisos`; FE Admin shows it after Alembic with no admin-ocs change. Precedent: `compras_020` catalog-only, no `roles_permisos_base`. Resolver already exists: `resolver_usuarios_con_algun_permiso` / `tienePermiso`. **Faltantes stay `pedido.responsable_id`** (and G31 `deposito.recibir_mercaderia`).

**Banners.** System alerts rotate with `max_alertas_visibles`. Compras banners in `AppLayout` stack every unread `compras.*` (API `limit: 50`), no cap. Persistent OK banners should not timed-rotate away; overflow needs “+N más”.

**#1323 undo.** `deshacer_recibido` already implements D-UNDO-R: `en_cuenta_corriente` iff `op_cuenta_corriente_id` set and `pagado_en` is null; else `pagado`. `controlado` → 409. Router uses `require_permiso(deposito.recibir_mercaderia)`. Tests cover pagado, CC (null `pagado_en`), controlado 409. Missing: second undo 409, CC + `pagado_en` → `pagado`, HTTP 403 without permission.

**#1324 multi-OC.** `TabRecepcionDeposito` drops empty blocks (`blockLineas.length === 0 → return null`). Linked OC with no ERP lines disappears. `desvincular_oc` deletes **all** `pedido_compra_ocs` + header cache (unlink-all). Spec has 1-of-2 controlado; no 1-of-3 test.

**Novedades.** Pattern: `frontend/src/novedades/YYYY-MM-DD-<slug>.md`, Spanish, “Cómo se usa”. One file for the whole stack. **Do not commit until Gabe reads the draft.**

**Delivery.** Fixes land on existing feature-branch-chain (not new PRs). Target **main**. Spanish UI; English SDD.

### Affected Areas

- `backend/app/services/oc_match/doc_refs.py` — writeback must also insert rows
- `backend/app/services/oc_match/worker.py` — same FOR UPDATE transaction
- `backend/app/services/pedidos_service.py` — shared alta / optional read-path seed
- `backend/alembic/versions/compras_044_pipeline_tipo_responsable_facturas.py` — 100-char + UNIQUE/dedupe
- `backend/app/models/pedido_factura_documento.py` — unique `(pedido_id, numero)`
- `backend/app/services/compras_alertas_service.py` — drop hardcoded roles
- `backend/app/services/notificacion_service.py` — reuse resolver (no new helper)
- new Alembic seed for `administracion.ver_alertas_factura` (hang after 045 / PR2 tip)
- `frontend/src/components/AppLayout.jsx` + `AppLayout.comprasBanners.test.jsx`
- `frontend/src/components/compras/TabRecepcionDeposito.jsx` (+ tests)
- `backend/tests/unit/test_pedido_factura_documentos.py`, `test_oc_match_doc_refs.py`, `test_compras_alertas_service.py`
- `backend/tests/integration/test_recepcion_deposito_endpoints.py`, `test_vincular_oc_multi.py`
- `frontend/src/novedades/2026-09-23-compras-pipeline-chicho-review-fixes.md` — draft only (commit gate)
- `docs/modulos/compras-guia-usuario.md` — desvincular-all note if no granular unlink

### Approaches

1. **Shared alta from writeback (locked)** — After `apply_writeback` sets the text column, insert row via `agregar_factura_documento` (or extracted persist) in the same worker transaction; skip casefold-dupes. Optional list-time `seed_factura_documentos` for legacy text-only rows.
   - Pros: One identity; chips + alerts stay consistent; worker already has session + lock
   - Cons: Writeback signature grows (session); OC Match then fans out alerts
   - Effort: Medium

2. **Read-path only (rejected)** — Seed rows when chips are computed; leave writeback text-only.
   - Pros: No worker change
   - Cons: Race, list-time writes, alerts still miss Match; violates “this feature READS what OC Match WRITES”
   - Effort: Low

3. **Factura recipients = permission only (locked)** — Seed `administracion.ver_alertas_factura` without default roles; `destinatarios_factura` = `resolver_usuarios_con_algun_permiso`.
   - Pros: Matches Compras `administracion.*` convention; Admin panel picks it up alone (admin-ocs)
   - Cons: Titular/sub-PM/Admin no longer auto-receive until assigned
   - Effort: Low

4. **Keep D-FANOUT union + extra permission (rejected)** — Would keep hardcoded MarcaPM/ADMIN.
   - Pros: Fewer missed alerts on deploy
   - Cons: Violates locked “NO hardcoded roles”
   - Effort: Low

5. **Banner cap + “+N más” (locked)** — Reuse `max_alertas_visibles` already loaded in `AppLayout`; show that many compras banners; remainder as “+N más”. No timed rotation of persistent OK items.
   - Pros: Same knob as system alerts; OK items stay until dismissed
   - Cons: Overflow not individually visible until a slot frees
   - Effort: Low

6. **Timed rotation of compras banners (rejected as primary)** — Persistent OK + rotation hides unpaid items.
   - Effort: Low

7. **#1324 empty block + product note (locked default)** — Always render the OC section; copy “OC no encontrada en ERP” (or log). Keep unlink-all; document asymmetry unless apply finds granular DELETE cheap.
   - Pros: Honest UI; no API change unless cheap
   - Cons: Unlink still all-or-nothing
   - Effort: Low

### Recommendation

Use **1 + 3 + 5 + 7**. Amend `compras_044` (not on main yet): truncate/filter tokens to 100, log/skip overflows, casefold-dedupe, UNIQUE `(pedido_id, numero)`. Optional read-path seed for legacy. Confirm D-UNDO-R in spec; add the three missing tests. Land on existing PRs: **PR1** sync+044, **PR2** permiso+banners, **PR3** undo tests, **PR4** empty-block + 1-of-3 + novedad tip. Draft novedad path is a **commit gate**. Target **main**.

admin-ocs: catalog = DB; prefer `administracion.ver_alertas_factura`; no code in that worktree. Coord: `/home/user/.herdr/worktrees/pricing-app/feature-admin-ocs/tmp-coord-compras-permiso-alertas.md`.

### Risks

- `compras_044` already applied on PR1 DBs — amend in place (fresh CI); follow-up Alembic only if rewrite is impossible
- Permission-only fan-out shrinks recipients until Admin assigns
- UNIQUE vs mixed-case tokens — casefold-dedupe at seed/writeback
- Shared alta fires alerts from OC Match — intended once permission is assigned
- Unlink-all surprise — product note or cheap granular DELETE on PR4

### Ready for Proposal

Yes. All listed decisions are locked by the user; no Gabe-blocking questions. Propose now; next phase is spec.
