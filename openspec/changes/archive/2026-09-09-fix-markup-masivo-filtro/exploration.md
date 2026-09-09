## Exploration: fix-markup-masivo-filtro

### Current State

**Symptom (confirmed facts):** With brand + con precio + con stock filters active, no row checkboxes selected, the Productos grid showed **18** products, but Acciones masivas (PR #1242) showed **~4000+**.

**How the grid loads products**

1. `Productos.jsx` composes `useProductosFilters` + `useProductosData`.
2. `construirFiltrosParams()` (`useProductosFilters.js` ~433–491) builds API params from filter state (`marcas`, `con_stock`, `con_precio`, etc.) — **no pagination**.
3. `cargarProductos()` (`useProductosData.js` 88–104) calls:
   ```js
   const params = { ...construirFiltrosParams(), page, page_size: pageSize };
   ```
   then `productosAPI.listar(params)`, sets `productos` and `totalProductos` from the same response.
4. Default `pageSize` is **50**; UI offers **9999 = "Todos"** (`Productos.jsx` 1545–1557). Backend listing allows `page_size` up to **10000** (`productos_listing.py` 288).
5. Results line: `Mostrando {productos.length} de {totalProductos}` (`Productos.jsx` 1539).
6. `productosOrdenados = productos` (identity alias, line 221) — no client-side re-filter.

**What Acciones masivas receives and how it counts**

```2711:2721:frontend/src/pages/Productos.jsx
{mostrarMarkupMasivoModal && (
  <AplicarMarkupMasivoModal
    ...
    productos={productosOrdenados}
```

```35:37:frontend/src/components/AplicarMarkupMasivoModal.jsx
const total = productos?.length ?? 0;
const itemIds = (productos || []).map((p) => p.item_id);
```

- Header/button copy use that `total` (“Acciones masivas — {total} productos visibles”).
- Apply sends **only** `item_ids` chunks (`MAX_ITEMS_POR_REQUEST = 100`) to `/precios/aplicar-markup-masivo` and `/productos/config-cuotas-masivo`.
- **Does not** read `productosSeleccionados` (checkboxes are for color lote / other UX only).
- **Does not** receive or send `filtros` / `filtrosActivos`.
- Copy claims: “Opera solo sobre los productos visibles en la grilla (página actual y filtros)” — i.e. **whatever is currently in the loaded `productos` array**, which is one API page (`page_size`), not necessarily `totalProductos`.

**Invariant (code-backed):** While the modal is open against current state,

`modal total === productos.length === first number in “Mostrando X de Y”`.

They cannot diverge by construction. A UI that truly shows `Mostrando 18 de 18` and a modal of ~4000 would require different `productos` than the grid is rendering — not explained by a separate catalog fetch inside the modal (there is none).

**Path that yields ~4000 in the modal**

- `productos.length ≈ 4000` requires the last successful `listar` to return ~4000 rows → practically **`pageSize === 9999` (“Todos”)** (or another large page size) **and** the list query matching ~4000 rows.
- Matching ~4000 with “brand + con precio + con stock” claimed active implies either those filters were **not present on the request that filled `productos`**, or they still matched a catalog-scale set. Filters are correctly wired in `construirFiltrosParams` when state is set; listing applies `marcas` / `con_stock` / `con_precio` (`productos_listing.py` ~595–621).

**Compare sibling bulk actions (filter-aware, server-side)**

| Action | Scope mechanism | Evidence |
|--------|-----------------|----------|
| `CalcularWebModal` | `filtrosActivos` → `body.filtros` → `/productos/calcular-web-masivo` | `Productos.jsx` 2628–2665; modal builds filtros |
| `CalcularPVPModal` | same pattern → `/productos/calcular-pvp-masivo` | `Productos.jsx` 2670–2708 |
| `recalcularCuotasMasivo` | builds `body.filtros` from filter state when `hayFiltros` | `useProductosInlineEditing.js` 196–264 |
| `AplicarMarkupMasivoModal` | client `productos` → `item_ids` only | no `filtros`; backend schema is `item_ids` max 100 (`pricing.py` 1233–1237) |

Shared backend comment on mass-write filters (`productos_shared.py` 583–602): operators read “aplicar filtros” as “the products I am looking at”; running unfiltered would **silently widen** the write set. Markup masivo is the outlier: it never participates in that contract.

**Checkboxes:** Confirmed unused by this modal. Empty selection does not fall back to filters; scope is always the loaded page array.

**Pagination text caveat:** Footer shows `(1 - ${pageSize} de ${totalProductos})` (`Productos.jsx` 2590) — uses configured `pageSize`, not `min(page*pageSize, total)`, so with “Todos” it can read like `1 - 9999 de N` even when fewer rows loaded.

### Affected Areas

- `frontend/src/components/AplicarMarkupMasivoModal.jsx` — total/itemIds from `productos.length`; chunked item_ids apply
- `frontend/src/pages/Productos.jsx` — passes `productosOrdenados` only; siblings pass `filtrosActivos`
- `frontend/src/hooks/useProductosData.js` — page-scoped `listar` populates modal input
- `frontend/src/hooks/useProductosFilters.js` — `construirFiltrosParams`, `pageSize` (incl. 9999)
- `frontend/src/hooks/useProductosInlineEditing.js` — reference pattern for filter-scoped bulk
- `frontend/src/components/CalcularWebModal.jsx` / `CalcularPVPModal.jsx` — reference UX/API for filtros
- `backend/app/api/endpoints/pricing.py` — `AplicarMarkupMasivoRequest` has **no** `filtros`
- `backend/app/api/endpoints/productos_pricing.py` — `config-cuotas-masivo` (item_ids path)
- `backend/app/api/endpoints/productos_shared.py` — fail-closed filter fold used by other masivos

### Approaches

1. **Align with CalcularWeb/PVP: send `filtrosActivos`, resolve scope server-side**
   - Pros: Same mental model as other Productos bulk writes; respects full filtered set regardless of `pageSize`; matches fail-closed commentary in `productos_shared`.
   - Cons: Backend work (filtros on markup/config endpoints or resolve-IDs step); must keep chunking/audit behavior; larger change.
   - Effort: Medium–High

2. **Client: when opening modal, fetch all matching IDs with `construirFiltrosParams()` (ignore page slice) and pass that list**
   - Pros: Frontend-only relative to approach 1; modal total matches `totalProductos` under filters.
   - Cons: Large ID payloads with “Todos”/wide filters; duplicates listing concerns; still item_ids-only API.
   - Effort: Medium

3. **Selection XOR filters UX**
   - If `productosSeleccionados.size > 0` → those IDs; else → filtered set (via 1 or 2); never silent full loaded page when filters imply a smaller `totalProductos`.
   - Pros: Matches checkbox mental model; empty selection + filters = filtered set.
   - Cons: Needs explicit rules when no filters and no selection (confirm full catalog?).
   - Effort: Medium (on top of 1 or 2)

4. **Guardrails only (warn / disable)**
   - Block or warn when `productos.length !== totalProductos` or when `pageSize === 9999` and count ≫ expected; force user to confirm.
   - Pros: Low effort mitigation.
   - Cons: Does not fix sibling inconsistency; easy to click through; does not explain/fix root scope model.
   - Effort: Low

### Recommendation

Prefer **Approach 1** (optionally layered with **3**): make Acciones masivas filter-scoped like Calcular Web / PVP / recalcular cuotas, so the operator’s active filters define the write set. Keep item_ids chunking for apply, but **derive** IDs from the filtered universe (server resolve or dedicated list-ids), not from the current page buffer.

Short-term guardrail (**4**) can ship first if needed, but should not be the sole fix: with `pageSize=9999`, “visible page” already is catalog-scale and the dangerous widen still happens whenever filters are missing from that buffer.

**On 18 vs ~4000:** Code says modal count equals `productos.length` (same array as the grid body / “Mostrando X”). The ~4000 figure is therefore the **loaded page array size** (almost certainly “Todos” / large `page_size` plus a wide list result). The “18” is either the filtered `totalProductos` the user expected (sibling-modal mental model), a marca-panel/stat cue, or a misread of “Mostrando X de Y” — not a second fetch inside the modal. Proposal/research should confirm the exact on-screen strings from the reporter if needed; the **scope bug class** (page buffer vs filtros) is already proven.

### Risks

- Applying markup/config to thousands of IDs from an unfiltered or under-filtered “Todos” page is a large destructive write (partial lots + repair).
- Adding `filtros` without fail-closed empty-set behavior could widen writes (see `aplicar_filtros_cross_db_masivo` commentary).
- Changing scope to full filtered set while UI still says “visibles / página actual” will confuse unless copy and confirmations are updated.
- Backend `item_ids` max 100 requires continued chunking; timeouts/partial failure UX already sensitive.

### Ready for Proposal

**Yes** — ready for `sdd-research` (optional: confirm reporter UI strings / pageSize) or directly `sdd-propose` with Approach 1 (+ optional selection XOR). Do not implement production code in explore.
