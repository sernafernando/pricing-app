# Proposal: feat-compras-oc-match-renglones-ean

## Intent

Operators reviewing OC Match jobs need the expand-below **renglones** table to work as a carga review grid: matched GBP EAN visible, denser columns, and quantity shown as units. Backend already returns `ean`; the table omits it and renders `cantidad` via `String(value)` (`"2.0000"` looks like money). Parent `feat-compras-oc-match` (PR #1304); amends ops-ux expand-below renglones.

## Scope

### In Scope
- Add matched `ean` (label **EAN**) after `#` / before Descripción.
- Column order exactly: `indice`, `ean`, `descripcion`, `cantidad`, `precio_unitario`, `moneda`, `match_estado`, `confianza`, `item_id`.
- Headers: `#`, `EAN`, `Descripción`, `Cantidad`, `P Unit`, `Moneda`, `Match`, `Confianza`, `Item`.
- Densify Descripción (less empty width); rebalance column widths.
- Format `cantidad` as units (`formatUnidades` style): trim trailing zeros; max 2 fraction digits if fractional.
- Keep `precio_unitario` at ~4 decimal places.
- FE-only: `TabOcMatch.jsx`, CSS if needed, `TabOcMatch.test.jsx`.
- Single small PR to `main` from `feat/compras-oc-match-renglones-ean` (`upstream/main`).

### Out of Scope
- Acta `<pre>` (unchanged).
- `ean_extract` column.
- Backend, schema, migration, Excel writer, acta generator, `useOcMatch.js`.
- Shared `DataTable` global styles.
- Acta → interactive carga tool (Approach C).

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `compras-oc-match-ui`: renglones table adds matched EAN, locked order/headers, denser Descripción, unidades-style `cantidad`.

## Approach

Approach A (locked): densify renglones only. Bind EAN to payload `ean` (not `ean_extract`). Null `ean` → "—". Prefer `RENGLON_COLUMNS` width props; local CSS only if needed. `title` on truncated Descripción. Do not change shared DataTable.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/src/components/compras/TabOcMatch.jsx` | Modified | Reorder/widths `RENGLON_COLUMNS`; add `ean`; format `cantidad` |
| `frontend/src/components/compras/TabOcMatch.module.css` | Modified | Local density helpers only if widths are insufficient |
| `frontend/src/components/compras/TabOcMatch.test.jsx` | Modified | Fixture `ean`; assert order/headers; no trailing `.0000` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Bind `ean_extract` by mistake | Low | Column field locked to `ean` |
| Over-tight Descripción truncates text | Med | Rebalance widths; `title` for full string |
| Fractional qty forced to integer | Low | Max 2 fraction digits, not integer-only |
| Shared DataTable style bleed | Low | Tab-local CSS / column props only |

## Rollback Plan

Revert the three TabOcMatch files. No migration or API rollback.

## Dependencies

- Parent `feat-compras-oc-match` (PR #1304) and ops-ux expand-below renglones. Payload already includes `ean`.

## Success Criteria

- [ ] Headers appear in locked order with EAN before Descripción.
- [ ] Matched `ean` is shown; null `ean` → "—".
- [ ] `cantidad` `"2.0000"` displays as units (no four trailing zeros); rare fractions keep ≤2 digits.
- [ ] `precio_unitario` still shows ~4 decimals.
- [ ] Acta `<pre>` and Excel/backend/schema unchanged.
