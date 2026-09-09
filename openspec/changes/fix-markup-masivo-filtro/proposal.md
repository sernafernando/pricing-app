# Proposal: Fix Acciones masivas filter scope

## Intent

Acciones masivas (PR #1242) must not silently target ~catalog-scale rows when filters imply a small set. Evidence: marca + con stock + con precio → Total **18**, modal **4291**, buffer widened while Total cards stayed **18**. Align scope with filtered `totalProductos`; confirm when target **> 50**.

## Scope

### In Scope
- Target = **full filtered set** (Mostrando 50 de 200 → apply **200**).
- No filters → apply full listing (e.g. **4199**).
- Confirm alert before apply when count **> 50**.
- Filter-scoped like Calcular Web/PVP (`filtros` or resolve IDs); keep **100**-ID chunks.
- Stop modal-open desync widening `productos` while stats stay filtered; drop “página actual” copy.

### Out of Scope
- Changing Calcular Web / PVP / recalcular-cuotas.
- Raising `item_ids` max_length beyond chunking.
- Checkbox selection XOR.
- Listing/pagination redesign.

## Capabilities

> `sdd-spec` contract. `openspec/specs/` has no Acciones masivas capability (rrhh-horas-extras, security-hardening, dashboard-query-performance only).

### New Capabilities
- `productos-acciones-masivas-scope`: write-set = full active-filter result (or full listing if unfiltered); modal count matches; confirm if > 50; fail-closed filter resolve; chunked apply.

### Modified Capabilities
- None

## Approach

Approach 1: pass `filtrosActivos` / resolve IDs like Calcular Web/PVP and `aplicar_filtros_cross_db_masivo`, then chunk into `/precios/aplicar-markup-masivo` and `/productos/config-cuotas-masivo`. Do not scope from the page `productos` buffer alone. Modal open must not unfiltered-widen `listar`. Confirm when count > 50.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/src/components/AplicarMarkupMasivoModal.jsx` | Modified | Filter-resolved count/IDs; >50 confirm; copy |
| `frontend/src/pages/Productos.jsx` | Modified | Pass filtros/resolved IDs; drop page-only scope |
| `frontend/src/hooks/useProductosData.js` | Modified | Prevent modal-open buffer widen |
| `backend/app/api/endpoints/pricing.py` | Modified | Filtros / resolve-IDs if needed |
| `backend/app/api/endpoints/productos_pricing.py` | Modified | Same for config-cuotas-masivo |
| `backend/app/api/endpoints/productos_shared.py` | Modified | Reuse fail-closed filter fold |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Empty/missing filtros widens writes | Med | Fail-closed; match sibling masivos |
| Partial batch failure on large applies | Med | Keep 100-chunk UX + clear errors |
| Stale “visibles/página” copy | Med | Strings use resolved count |

## Rollback Plan

Revert PR/branch to page-buffer `item_ids` + prior copy. No migrations expected. Applied lots need data repair, not code rollback.

## Dependencies

- Preproposal rev **6** confirmed decisions.
- Sibling: CalcularWeb/PVP, recalcularCuotas, `productos_shared` fold.
- Evidence: `evidence/2026-09-04-grid-mostrando-18.png`, `evidence/2026-09-04-modal-4291.png`.

## Success Criteria

- [ ] Filtered Total **18** → modal targets **18** (not ~4291); Total cards stay in sync.
- [ ] Mostrando 50 de 200 → apply **200**; unfiltered ~4199 → **4199**.
- [ ] Count > 50 requires confirm; ≤50 does not.
- [ ] Chunks of 100 retained; Calcular Web/PVP unchanged.
