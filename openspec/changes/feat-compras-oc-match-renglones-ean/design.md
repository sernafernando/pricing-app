# Design: feat-compras-oc-match-renglones-ean

## Technical Approach

FE-only densify of the expand-below renglones grid (proposal Approach A; delta spec `compras-oc-match-ui`). Backend already returns matched `ean`. Implementation stays inside `TabOcMatch`: reorder `RENGLON_COLUMNS`, bind `ean`, format `cantidad` as units, keep `precio_unitario` at ~4dp, cap Descripción empty width. Shared `DataTable` and acta `<pre>` stay untouched.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|----------|---------|----------|--------|
| EAN source | payload `ean` vs `ean_extract` | extract is proforma; operators want matched GBP | Bind `ean`; null/empty → "—" |
| Column lock | custom header row vs `RENGLON_COLUMNS` | DataTable already renders from the array | Reorder + relabel `RENGLON_COLUMNS` only |
| Density | change `DataTable.module.css` vs local widths | Global CSS bleeds to other compras tabs | Column `width` props + bump renglones `minWidth`; local `.tdTruncate` only if needed |
| Qty format | extract shared util vs local helper vs `String` | `formatUnidades` in `TabRecepcionDeposito` is private | Local `formatCantidad` with the same `toLocaleString('es-AR', { maximumFractionDigits: 2 })` |
| Precio | unidades trim vs keep 4dp | trim would hide money precision | Local `formatPrecioUnitario` with min/max 4 fraction digits |
| Truncation title | add DataTable `cellClass` vs wrap span | DataTable has no cell-class slot | `<span className={styles.tdTruncate} title={full}>` |
| Acta / hook / Excel | leave vs Approach C | locked out of scope | Unchanged |

## Data Flow

```
useOcMatch selected.renglones (ean already on payload)
        │
        ▼
DataTable(RENGLON_COLUMNS, renderCell)
        │
        ├─ ean             → value or "—"  (.tdMono)
        ├─ descripcion     → truncate span + title=full string
        ├─ cantidad        → formatCantidad
        ├─ precio_unitario → formatPrecioUnitario (~4dp)
        └─ confianza       → ConfianzaBadge (unchanged)
```

No new fetch. `useOcMatch` and job list table stay as-is.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/compras/TabOcMatch.jsx` | Modify | Reorder/relabel `RENGLON_COLUMNS`; add `ean`; local formatters; Descripción title; renglones `minWidth` ≈ `820px` |
| `frontend/src/components/compras/TabOcMatch.module.css` | Modify | Add `.tdTruncate` (ellipsis, nowrap). Do not edit `.acta` |
| `frontend/src/components/compras/TabOcMatch.test.jsx` | Modify | Fixture `ean` + `"2.0000"`; assert headers, EAN, qty, precio, no `ean_extract` |

Do not touch: `DataTable.jsx`, `DataTable.module.css`, `useOcMatch.js`, backend, Excel, acta generator.

## Interfaces / Contracts

Locked `RENGLON_COLUMNS` (field / header / width / align):

| key | label | width | align |
|-----|-------|-------|-------|
| `indice` | `#` | `40px` | left |
| `ean` | `EAN` | `128px` | left |
| `descripcion` | `Descripción` | `180px` | left |
| `cantidad` | `Cantidad` | `72px` | right |
| `precio_unitario` | `P Unit` | `80px` | right |
| `moneda` | `Moneda` | `64px` | left |
| `match_estado` | `Match` | `88px` | left |
| `confianza` | `Confianza` | `88px` | left |
| `item_id` | `Item` | `72px` | left |

DataTable already applies widths via `<colgroup>` and `table-layout: fixed`. Current renglones `minWidth="480px"` is too tight once EAN is added; set ≈ `820px` (sum of explicit widths). Extra leftover must not stay on an unbounded Descripción — every column gets a width.

Non-obvious formatters (module-level, same file as `formatDateTime`; do not extract `formatUnidades`):

```js
const formatCantidad = (v) => {
  if (v == null || v === '') return '—';
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString('es-AR', { maximumFractionDigits: 2 });
};

const formatPrecioUnitario = (v) => {
  if (v == null || v === '') return '—';
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString('es-AR', {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });
};
```

`.tdTruncate`: `display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;` (CF tokens only if color/spacing is needed). Always set `title` to the full Descripción.

`renderCell` keeps the `confianza` badge branch; other keys use the formatters above or `String(value)` / "—".

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Headers `# EAN Descripción Cantidad P Unit Moneda Match Confianza Item`; EAN value; null ean `"—"`; `"2.0000"` displays as `2` (no four trailing zeros); `"0.5000"` keeps ≤2 fraction digits; `"12.3456"` still ~4dp; no `ean_extract` header; acta text unchanged | Extend `TabOcMatch.test.jsx` fixtures |
| Integration | N/A | No API/hook change |
| E2E | N/A | Browser density check after apply |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration required. Single PR from `feat/compras-oc-match-renglones-ean` to `main`. Rollback: revert the three TabOcMatch files.

## Open Questions

None. Approach A and column/format locks are in `state.yaml`.
