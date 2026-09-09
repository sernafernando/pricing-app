# Design: Stable paging for Acciones masivas resolve

## Decisions

| Topic | Choice | Why |
|-------|--------|-----|
| Stable order | Always send `orden_campos: 'item_id'`, `orden_direcciones: 'asc'` from `buildListarParamsFromFiltros` | Matches listing lesson elsewhere (`order_by(ProductoERP.item_id.asc())`); ties do not reshuffle across OFFSET pages |
| Dedupe | Accumulate with `Set`, return `[...set]` | Makes duplicate+omit show up as length mismatch vs Total |
| Mismatch gate | Outside `filtersActive`; only empty-with-filters stays gated | Unfiltered catalog is the largest write-set — must still verify vs finite Total |
| Loop ceiling | `maxPages = ceil(expectedTotal / pageSize) + 2` (floor at least 2); if exceeded → `ResolveFilteredIdsError` code `api` or `mismatch` | Prevents hang when backend omits `total` and keeps returning full pages |

## Non-goals

- Changing backend default ORDER BY for all listar callers
- Merging PR2 into PR1 (merge order remains tracker chain; reply confirms that)
