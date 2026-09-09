# Tasks: Acciones masivas markup 0 and negative

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 180–320 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Commits on existing PR #2 (`fix/markup-masivo-02-wiring-desync`) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 0 | Rebase onto `main` | PR #2 | `pytest tests/unit/test_acciones_masivas_schemas.py` + `pnpm test src/components/AplicarMarkupMasivoModal.test.jsx` | N/A — git hygiene | Abort rebase |
| 1 | Schema 0/negative | PR #2 | `pytest tests/unit/test_acciones_masivas_schemas.py -q` | N/A — Pydantic unit only | `pricing.py` field + schema tests |
| 2 | Modal Tesla stack | PR #2 | `pnpm test src/components/AplicarMarkupMasivoModal.test.jsx` | Productos Acciones masivas: 0 ≤50 no negative pane; −3 CS-4 then write; −3+>50 stack | modal jsx/css/test |

## Phase 0: Rebase / hygiene (WU0)

- [x] 0.1 Rebase `fix/markup-masivo-02-wiring-desync` onto upstream `main` (#1245). Keep PR2 desync/resolve; do not reopen #1244.

## Phase 1: Backend schema (WU1)

- [x] 1.1 RED: invert `test_aplicar_markup_masivo_requiere_markup_positivo` in `backend/tests/unit/test_acciones_masivas_schemas.py`; accept 0 and −5; reject inf/NaN; keep `item_ids` 1–100.
- [x] 1.2 GREEN: `AplicarMarkupMasivoRequest.markup_objetivo` in `backend/app/api/endpoints/pricing.py` — drop `gt=0`, set `Field(..., allow_inf_nan=False)`. Spec: Backend schema accepts zero and negative.

## Phase 2: Modal UX (WU2)

- [x] 2.1 RED in `frontend/src/components/AplicarMarkupMasivoModal.test.jsx`: 0 ≤50 writes, no MarkUp Negativo; blur keeps 0/−3; NaN/empty toast, no write; negative CS-4 then write; Volver aborts, value intact; −3 then >50 stack; 0+>50 volume only; no `window.confirm`. Keep >50/chunk/fail-closed tests.
- [x] 2.2 GREEN `frontend/src/components/AplicarMarkupMasivoModal.jsx`: `Number.isFinite`; allow 0/negative; onBlur reset only non-finite to `5.0`; toast drop “mayor a 0”; `confirmacion.gate` `'negative'|'threshold'`; negative pane then >50; Volver/Escape/X clear pane, no write; never `window.confirm`. Copy from `frontend/src/pages/Productos.jsx` (read-only): title MarkUp Negativo, CTA Guardar de todas formas (no emoji).
- [x] 2.3 Optional danger title token on negative pane in `frontend/src/components/AplicarMarkupMasivoModal.module.css`; reuse `.confirmacion`; CF tokens; no emoji.

## Phase 3: Cleanup

- [x] 3.1 Do not change calculator, cuotas 0–100, row CS-4, resolve helper, or `useProductosData` request-generation guard.
