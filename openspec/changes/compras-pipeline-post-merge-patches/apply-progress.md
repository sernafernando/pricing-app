# Apply Progress: compras-pipeline-post-merge-patches

**Change**: compras-pipeline-post-merge-patches
**Mode**: Standard
**Delivery**: single-pr
**Branch**: `feat/compras-pipeline-post-merge-patches`
**Updated**: 2026-09-24 (Phase 6 visual addendum)

## Completed Tasks

- [x] 1.1 NC/ND known + aliases in `doc_refs.py`; `TIPOS_ROUTEABLE` unchanged
- [x] 1.2 Prompt enum + NC/ND copy; `quote_numeric_doc_fields` + stringify; `transform_text` before `json.loads`
- [x] 1.3 Match passes `nro_*` as strings via `_token_as_str`
- [x] 2.1 Worker skips write-back/stamp/`persist_factura_documento` for NC/ND
- [x] 2.2 `GET /pedidos?excluir_estado=` applied only when `estado` is None
- [x] 3.1 Shared `stripPedidoQueryParams` / `consumePedidoQuery` / `nextPedidoOpenNonce`
- [x] 3.2 Pedidos default `excluir_estado=cancelado`; logistic ESTADOS; consume + Ver nonce
- [x] 3.3 User Compras tab click strips `pedido`/`focus`/`open`; inbound `tab=` sync unchanged
- [x] 3.4 Banner `open` nonce; factura Ver → `/ok` then navigate; faltantes X → snooze; faltantes Ver navigate-only
- [x] 3.5 Depósito chips split on `;`; `incluirCC` defaults `true`
- [x] 3.6 REMOVED — ModalPedidoDetalle `Boolean(row.cargada)` left unchanged
- [x] 3.7 Novedad amended: Incluir CC defaults on; Pedidos default omits cancelados
- [x] 4.1–4.5 Focused backend + frontend tests
- [x] 5.1 Semantic Proceso chip tones (OC info, Factura success, Match error danger, other Match warning; eje badges stronger; Número muted)
- [x] 5.2 Estado `con_faltantes` cell widened + overflow/z-index so badge stays visible beside Proceso
- [x] 5.3 Vitest: Factura vs Match-error `data-tone`; estado-cell `data-layout=no-clip`
- [x] 6.1 Visual vitest: Chromium computed OC/Factura/Match-error token colors + Con faltantes vs Proceso geometry

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command and exact result | Phases 1–4: pytest 46 + vitest 86. Phase 5: `pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx` → **12 passed**. Phase 6: `pnpm exec vitest run --project=visual src/test/visual/tabPedidosCompraChips.visual.test.jsx` → **2 passed**; unit `TabPedidosCompra.test.jsx` still **12 passed**. |
| Runtime harness command/scenario and exact result | N/A — no routing/shell/process-integration boundary; threat matrix in design is N/A. Visual project is Playwright Chromium computed-style, not a 5m sweep. |
| Rollback boundary | Revert this branch / the apply commits. No Alembic. Extract/persist, Pedidos filter, and query-lifecycle FE revert independently. Unchanged: `TabOcMatch.*`, `compras_alertas_service` 5m/PM, CAS, freeze-migration. Phase 6 is the visual test file + SDD artifact notes only. |

## Deviations from Design

Phase 6: mocked `useSearchParams` instead of wrapping with `MemoryRouter`. Importing `react-router-dom` live in the visual project makes Vite optimize it mid-run, reload the page, and throw invalid hook call (`useRef` null). The hook mock is enough — TabPedidosCompra only reads search params.

## Issues Found

GGA pre-commit reviews the whole file, not the hunk. First backend commit bundled `administracion_compras.py` and failed on pre-existing health/auth, naive `datetime.now`, missing `response_model`, and N+1 — not on `excluir_estado`. Frontend commit failed on pre-existing ~200-line god-component size for `TabPedidosCompra` / `AppLayout`. Documented both with `ponytail:` + `docs/tech-debt-ledger.md` (same pattern as `TabRecepcionDeposito`). Did not split components or rewrite the god-router (out of scope / locks).

## Locks respected

- No `TabOcMatch.*` edits
- No expand-below
- No Alembic
- No `compras_alertas_service` 5m/PM sweep
- No CAS / freeze-migration
