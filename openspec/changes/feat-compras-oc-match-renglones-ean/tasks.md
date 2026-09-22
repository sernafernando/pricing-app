# Tasks: feat-compras-oc-match-renglones-ean

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 40–120 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Branch + renglones EAN/order/format + Vitest | PR 1 | `pnpm exec vitest run src/components/compras/TabOcMatch.test.jsx` | N/A — jsdom; browser density after apply | Revert three TabOcMatch files + apply-progress |

## Phase 1: Branch

- [x] 1.1 Create `feat/compras-oc-match-renglones-ean` from `upstream/main` (not develop). Do not commit to main.

## Phase 2: RENGLON_COLUMNS

- [x] 2.1 In `frontend/src/components/compras/TabOcMatch.jsx` lock `RENGLON_COLUMNS` to: `indice` `#` 40px; `ean` `EAN` 128px; `descripcion` `Descripción` 180px; `cantidad` `Cantidad` 72px right; `precio_unitario` `P Unit` 80px right; `moneda` `Moneda` 64px; `match_estado` `Match` 88px; `confianza` `Confianza` 88px; `item_id` `Item` 72px. Bind `ean` not `ean_extract`.
- [x] 2.2 In `frontend/src/components/compras/TabOcMatch.jsx` set renglones DataTable `minWidth` to `820px`. Leave job-list `minWidth` unchanged.

## Phase 3: Formatters and density

- [x] 3.1 In `frontend/src/components/compras/TabOcMatch.jsx` add module-level `formatCantidad` (`es-AR`, max 2 fraction digits; null/empty → "—"; NaN → `String(v)`) and `formatPrecioUnitario` (min/max 4dp; same null/NaN). Do not extract `formatUnidades`.
- [x] 3.2 In renglones `renderCell` of `frontend/src/components/compras/TabOcMatch.jsx`: keep `confianza` badge; `ean` → value or "—" + `.tdMono`; `descripcion` → `<span className={styles.tdTruncate} title={full}>`; `cantidad`/`precio_unitario` use formatters. Do not edit `frontend/src/hooks/useOcMatch.js` (read-only), `frontend/src/components/compras/_shared/DataTable.jsx` (read-only), or `frontend/src/components/compras/_shared/DataTable.module.css` (read-only).
- [x] 3.3 In `frontend/src/components/compras/TabOcMatch.module.css` add `.tdTruncate` (`display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap`). Do not edit `.acta`.

## Phase 4: Vitest

- [x] 4.1 In `frontend/src/components/compras/TabOcMatch.test.jsx` fixture: `ean: '7791234567890'`; second renglon `ean: null`; `cantidad` `'2.0000'` and `'0.5000'`; `precio_unitario: '12.3456'`; include `ean_extract` on payload.
- [x] 4.2 Assert headers `# EAN Descripción Cantidad P Unit Moneda Match Confianza Item`; EAN `7791234567890`; null ean "—"; qty `2` (no `.0000`); `0.5000` ≤2 digits not integer-forced; P Unit ~4dp (`12,3456` es-AR).
- [x] 4.3 Assert no `ean_extract` header; acta `<pre>` text unchanged. Run `pnpm exec vitest run src/components/compras/TabOcMatch.test.jsx`.

## Phase 5: Apply-progress

- [x] 5.1 Write `openspec/changes/feat-compras-oc-match-renglones-ean/apply-progress.md`: completed tasks, focused test, N/A runtime harness, rollback = three TabOcMatch files. Skip `frontend/src/novedades/2026-09-21-oc-match.md` (read-only) — proposal/design FE TabOcMatch only.
