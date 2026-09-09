# Tasks: Fix Acciones masivas filter scope

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 280–420 |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR1 resolve+modal → PR2 wiring+desync guard |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No — user chose feature-branch-chain
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Client ID resolve + modal scope/confirm/chunks | PR 1 | `cd frontend && npm test -- AplicarMarkupMasivoModal` | N/A — Vitest mocks cover resolve/confirm; manual smoke optional | Revert modal + resolve helper only |
| 2 | Productos props + listar/stats generation guard | PR 2 (base=PR1) | `cd frontend && npm test -- useProductosData` | N/A — hook unit covers stale race; optional open/cancel smoke | Revert `Productos.jsx` + `useProductosData.js` only |

## Phase 1: Foundation — resolve helper

- [x] 1.1 Extract/reuse filter→`listar` params from `construirFiltrosParams` / `exportFilterParams.js` into a small shared resolve helper (create or extend) that pages filtered `productosAPI.listar` until all `item_id`s collected.
- [x] 1.2 Helper fail-closed: if filters active and resolve empty or length mismatches `totalProductos`, refuse (no page-buffer fallback).

## Phase 2: Core — modal write-set + confirm

- [x] 2.1 In `AplicarMarkupMasivoModal.jsx`, replace `productos` scope with props `filtrosActivos` + `totalProductos`; display count = `totalProductos` / resolved size, never `productos.length`.
- [x] 2.2 Remove “página actual” / page-only visibles copy; strings use resolved count.
- [x] 2.3 On apply: if count > 50, Tesla in-modal confirm before any write; if ≤ 50, skip that gate (same threshold as `CalcularWebModal`; no `window.confirm`).
- [x] 2.4 On apply: resolve IDs via helper into modal-local state only; keep `chunkIds(..., 100)` to existing HTTP endpoints `precios/aplicar-markup-masivo` (read-only) and `productos/config-cuotas-masivo` (read-only) (no backend schema change).

## Phase 3: Integration — wiring + desync guard

- [x] 3.1 In `Productos.jsx`, pass `filtrosActivos` (same shape as Calcular Web ~2635) + `totalProductos`; stop passing `productos` as scope; open path must not call `cargarProductos`/`setProductos`.
- [x] 3.2 In `useProductosData.js`, add request-generation guard on `cargarProductos`/`cargarStats` so stale/unfiltered responses cannot desync buffer vs Total cards.

## Phase 4: Testing (spec scenarios)

- [x] 4.1 Create/extend `AplicarMarkupMasivoModal.test.jsx`: modal count = filtered total 18 not page buffer; Total 200 page 50 → resolve/apply 200 IDs; unfiltered N → N.
- [x] 4.2 Same test file: count > 50 requires `confirm` before writes; count ≤ 50 skips confirm; empty/mismatch resolve fails closed (no catalog widen); 200 IDs → chunks ≤ 100.
- [x] 4.3 Add/extend `useProductosData` unit test: overlapping listar/stats — stale response ignored (desync guard).
- [x] 4.4 Smoke-check `Productos.jsx` wiring: open then cancel leaves Total/stats/filter semantics unchanged (unit or light page test).

## Phase 5: Cleanup

- [x] 5.1 Confirm no edits to backend `backend/app/api/endpoints/pricing.py` (read-only) / `backend/app/api/endpoints/productos_pricing.py` (read-only) / `backend/app/api/endpoints/productos_shared.py` (read-only) or Calcular Web/PVP components (read-only).
- [x] 5.2 Finalize modal header/CTA copy using resolved count (open question from design).
