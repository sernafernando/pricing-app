# Design: Fix Acciones masivas filter scope

## Technical Approach

Stop scoping Acciones masivas from the page `productos` buffer. Mirror Calcular Web/PVP: **active filters define the write-set**. Resolve the full filtered ID list on the client (same params as `construirFiltrosParams`), then apply via existing chunked `item_ids` endpoints (max 100). Modal count = resolved set / `totalProductos`, never `productos.length`. Confirm when count > 50. Spec: `productos-acciones-masivas-scope`.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|----------|---------|----------|--------|
| Write-set source | Page buffer vs full filter result | Buffer ≠ Total; PR #1242 review warned | **Full filter result** (`totalProductos` / resolve) |
| How to get IDs | Filtros on write endpoints vs client resolve + keep `item_ids` chunks vs new resolve API | Server filtros = unbounded one-shot (sibling pattern) but markup already chunks for UX/timeouts; new API = more surface | **Client resolve via filtered `listar` pages** + keep `/precios/aplicar-markup-masivo` + `/productos/config-cuotas-masivo` unchanged |
| Fail-closed | Silent widen vs refuse | Sibling `aplicar_filtros_cross_db_masivo` refuses widen | **Refuse** if hayFiltros and resolve empty/mismatch; never fall back to page buffer |
| Modal open vs listing | Open mutates `productos` vs ephemeral resolve | Observed: Mostrando→4291 while Total cards stayed 18 | **Open must not call `cargarProductos` / `setProductos`**; resolve into modal-local state only |
| >50 confirm | Always / never / threshold 50 | Product decision | **Tesla in-modal confirm before any write when count > 50** (same gate as `CalcularWebModal`; UI follows `frontend/AGENTS.md`, not `window.confirm`) |
| Backend write schemas | Add `filtros` to markup/config vs leave | Adding filtros without chunk protocol risks timeouts | **No schema change** this change |

### Modal-open desync (investigation)

Current open path (`Productos.jsx` ~799–800): only `setMostrarMarkupMasivoModal(true)` — **no** `listar`. Modal total = `productos.length` (`AplicarMarkupMasivoModal.jsx` 35–37). Observed widen (Mostrando/modal ~4291, Total cards 18) requires `setProductos`/`setTotalProductos` from a wide `listar` while `stats` (`cargarStats` → `stats.total_productos`) stayed filtered — separate effects in `useProductosData.js` with **no request generation/abort**, so a stale or unfiltered `cargarProductos` can land after filtered stats (e.g. race after filter clear via Total Productos `onClick={limpiarFiltros}`). Design prevention: (1) stop using page buffer for scope; (2) never write resolve results into page `productos`; (3) add a **request-generation guard** on `cargarProductos`/`cargarStats` so stale responses cannot desync buffer vs stats.

## Data Flow

```
Productos (filtrosActivos + totalProductos)
    │ open Acciones masivas — no listar / no setProductos
    ▼
AplicarMarkupMasivoModal (display count = totalProductos | resolved.length)
    │ apply → if count>50 confirm
    │ resolve IDs: productosAPI.listar({...construirFiltrosParams(), page, page_size})
    │   loop pages until all item_ids collected; fail-closed on empty/mismatch
    │ chunkIds(ids, 100)
    ├─► POST /productos/config-cuotas-masivo { item_ids }  (unchanged)
    └─► POST /precios/aplicar-markup-masivo { item_ids, ... } (unchanged)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/AplicarMarkupMasivoModal.jsx` | Modify | Accept `filtrosActivos` + `totalProductos` (or resolve helper); drop page-buffer count/copy; >50 confirm; resolve+chunk apply |
| `frontend/src/pages/Productos.jsx` | Modify | Pass same `filtrosActivos` shape as Calcular Web (~2635); stop passing `productos` as scope source |
| `frontend/src/hooks/useProductosData.js` | Modify | Request-generation guard on listar/stats; ensure modal open never triggers load |
| `frontend/src/components/exportFilterParams.js` or small shared helper | Modify/Create | Reuse filter→API body mapping already used by CalcularWeb / listar params |
| `frontend/src/components/AplicarMarkupMasivoModal.test.jsx` (or sibling) | Create/Modify | Scope count, >50 confirm, fail-closed, no page-buffer |
| `backend/.../pricing.py`, `productos_pricing.py`, `productos_shared.py` | **No change** | Keep max-100 `item_ids`; fail-closed fold stays for siblings only |

## Interfaces / Contracts

```js
// Modal props (target)
{ filtrosActivos, totalProductos, showToast, puedeEditarCuotas, onClose, onSuccess }
// Resolve: same filter keys as CalcularWebModal body.filtros / construirFiltrosParams
// Writes: unchanged AplicarMarkupMasivoRequest / ConfigCuotasMasivoRequest (item_ids ≤ 100)
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Modal count from `totalProductos`; >50 gates confirm; empty resolve refuses | Vitest + mocked `listar`/api |
| Unit | `cargarProductos` ignores stale response | Hook test with overlapping calls |
| Integration | Filtered Total 18 → apply 18 IDs in chunks | Mock API sequence |
| E2E | Optional smoke: open modal does not change Total cards | Manual / Playwright if present |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration. Ship behind normal PR; rollback = revert frontend scope change.

## Open Questions

- [x] Filtros-on-write-endpoint path rejected: would bypass proven 100-chunk UX or require new offset protocol.
- [ ] Exact copy string for header/CTA once “visibles/página actual” is removed (use resolved count; finalize in apply).
