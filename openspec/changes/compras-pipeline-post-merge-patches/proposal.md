# Proposal: Compras Pipeline Post-Merge Patches

## Intent

Fix Gabe post-#1340 Compras bugs without amending `compras-faltantes-responsable-cas` / `compras-pipeline-reqs-closure`, and without regressing the 5m factura-cargada timer, CAS resolver, or freeze-migration.

## Scope

### In Scope
- Ignore NC/ND in OC-match extract/writeback. Attach only `factura` / `pedido` / `nota_venta` / `proforma`. Defense in depth: prompt enum + normalize + skip `persist_factura_documento` for NC/ND.
- Pedido tokens are strings end-to-end; Depósito chips keep leading zeros.
- Pedidos default = all estados except `cancelado`; Cancelado selectable; add `recibido`, `con_faltantes`, `controlado`.
- **Banner dismiss (Gabe lock):**
  - `factura_cargada` (y demás no-faltantes): **X** y **Ver** → `PATCH /ok` definitivo (Ver luego navega).
  - `compras.faltantes`: **sí se puede cerrar con X** (hoy no); X = **Posponer**/`/snooze` (~1h, vuelve si no hay resolución — sin cambiar esa ventana). **Ver** solo navega (no `/ok`, no snooze). Cierre definitivo = texto de resolución → resuelto (sin cambios).
- Ver/banner no-ops + sticky reopen: close or Compras tab change MUST clear or remount-safe `?pedido=` / focus; Ver MUST force-open if URL unchanged.
- Depósito filter toggle **Incluir cuenta corriente** default MUST be **on** (`true`); was shipped `false`.
- Amend existing novedad `2026-09-23-compras-pipeline-ux.md` for CC default + Pedidos filter (no new novedad file for bugfixes).

### Out of Scope
OC-match expand-below (defers to oc-match owners; amends `feat-compras-oc-match-ops-ux`). Amending the two locked changes; Alembic unless proven; persist NC/ND; email/Slack. **Not** inventing a new factura-checkbox model (misread of item 4 — dropped).

## Capabilities

### New Capabilities
None

### Modified Capabilities
- `compras-oc-match-pipeline`: NC/ND non-routeable; enum + normalize + persist gate; string tokens.
- `compras-factura-documentos`: OC-match MUST NOT create factura rows from NC/ND.
- `recepcion-deposito`: pedido chips show the stored string (keep leading zeros); Incluir CC toggle defaults on.
- `pedidos-compra`: default excludes only `cancelado`; dropdown adds logistic estados; `?pedido=` lifecycle + force-open Ver.
- `compras-pipeline-alerts`: Ver dismisses dismissible banners via `/ok` (like X); force-open; no stale-query reopen; faltantes Ver still no `/ok`.
- ~~checkbox stuck~~ — **removed** (wrong interpretation of Gabe item 4).

## Approach

Prompt enum + normalize NC/ND as non-routeable; persist skips `persist_factura_documento` and factura write-back. Keep `nro_pedido` as string through chip. Default Pedidos omits `cancelado` only. Consume-or-clear `pedido`/`focus` on close and tab change; Ver/banner use a focus nonce so the same URL still opens.

## Affected Areas

- Modified: `oc_match/{extract,doc_refs,worker}.py` (NC/ND ignore; string tokens)
- Modified: `TabPedidosCompra.jsx`, `TabRecepcionDeposito.jsx` (filter, query lifecycle, chips)
- Modified: `ModalPedidoDetalle.jsx`, `AppLayout.jsx`, `AlertBanner.jsx` (clear query; force-open Ver)
- Unchanged: `TabOcMatch.jsx` (expand-below deferred)

## Risks

- Gemini labels NC as `factura` (Med): persist gate + tests
- Clearing `?pedido=` breaks inbound land (Med): clear only after consume/close/tab change
- Checkbox fix regresses 5m / PM notify (Med): UI binding only; leave sweep/timer

## Rollback Plan

Revert the patch PR. No Alembic expected. Extract/persist, filter, and query-lifecycle FE revert independently.

## Dependencies

Merged #1340. Existing `AlertBanner`, `deepLinkForCompras`, `persist_factura_documento`, 5m undo.

## Success Criteria

- [ ] NC/ND never attach as factura; only factura/pedido/nota_venta/proforma write back.
- [ ] Leading zeros survive extract → persist → chips.
- [ ] Default omits cancelado; Cancelado + recibido/con_faltantes/controlado selectable.
- [ ] Factura banner: Ver and X dismiss permanently via `/ok`; refresh must not bring it back.
- [ ] Faltantes: X snoozes (~1h, returns if unresolved); Ver navigates only; permanent clear stays on resolution texto.
- [ ] Ver/banner force-open if URL already has `?pedido=`; close or tab change does not sticky-reopen.
- [ ] Depósito "Incluir cuenta corriente" defaults checked; user can still turn off.
