# Tasks: Compras Pipeline Post-Merge Patches

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 280–380 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | NC/ND + zeros + Pedidos filter/query + chips | PR1 `feat/compras-pipeline-post-merge-patches` | `pytest tests/unit/test_oc_match_doc_refs.py tests/unit/test_oc_match_pipeline.py tests/integration/test_oc_match_worker.py tests/integration/test_compras_endpoints.py -k 'excluir or listar_pedidos_estado' -q` + `pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx src/components/compras/TabRecepcionDeposito.test.jsx src/components/compras/ModalPedidoDetalle.test.jsx src/components/AppLayout.comprasBanners.test.jsx` | N/A — unit/integration + vitest; no 5m sweep edit | revert this branch |

Locks: no `TabOcMatch.*`; no expand-below; no Alembic; no `compras_alertas_service` 5m/PM; no CAS/freeze-migration.

### Commit / PR plan

Create `feat/compras-pipeline-post-merge-patches` from this worktree #1340 tip (`feat/compras-faltantes-responsable-cas`), not `origin/develop`. Check 2026-09-24: `origin/develop` lags `upstream/main` by 3595 and `upstream/develop` by 2119; no `origin/main`. Single PR to `develop` after the #1340 line is the base. Optional commits: backend → frontend → tests.

## Phase 1: Backend extract / normalize

- [x] 1.1 In `backend/app/services/oc_match/doc_refs.py` add `nota_credito`/`nota_debito` to `TIPOS_CONOCIDOS` + aliases `nc`/`nd`/`nota de credito`/`nota_de_credito`/`nota de debito`/`nota_de_debito`. Keep `TIPOS_ROUTEABLE` unchanged. (`oc-extract`, `oc-route`)
- [x] 1.2 In `backend/app/services/oc_match/extract.py` extend prompt enum + NC/ND copy; add `quote_numeric_doc_fields` so `00184465` stays a string; stringify `nro_*`. In `backend/app/services/oc_match/gemini_pool.py` run optional `transform_text` before `json.loads`. (`oc-extract`)
- [x] 1.3 In `backend/app/services/oc_match/match.py` pass `nro_pedido`/`nro_documento` as strings; never `int()`. (`oc-extract`)

## Phase 2: Backend persist + list API

- [x] 2.1 In `backend/app/services/oc_match/worker.py` skip `persist_factura_documento` when `normalize_tipo` is `nota_credito`/`nota_debito`; no stamp/write-back. Factura still seeds constancia `cargada=false`. (`oc-route`, `fact-nc`)
- [x] 2.2 In `backend/app/routers/administracion_compras.py` add `excluir_estado` Query on `listar_pedidos`; apply `~estado.in_()` only when `estado` is None. Explicit `estado=` wins. (`ped-filter`)

## Phase 3: Frontend

- [x] 3.1 In `frontend/src/hooks/useRecepcionDeposito.js` add shared strip of `pedido`/`focus`/`open` (`replace: true`; keep `tab`/`eje`/OP keys). (`ped-query`, `alert-open`)
- [x] 3.2 In `frontend/src/components/compras/TabPedidosCompra.jsx` default `excluir_estado=cancelado` (empty select ≠ all); add `recibido`/`con_faltantes`/`controlado` to `ESTADOS`; consume query after open; Ver adds `open` nonce. (`ped-filter`, `ped-query`, `alert-open`)
- [x] 3.3 In `frontend/src/pages/AdministracionCompras.jsx` user tab click strips `pedido`/`focus`/`open`; do not strip inbound `tab=` sync before first consume. (`ped-query`, `alert-open`)
- [x] 3.4 In `frontend/src/components/AppLayout.jsx` `deepLinkForCompras` appends `open=<nonce>`. Banner rules: (a) `compras.factura_cargada` and other non-faltantes: **Ver** → `handleOkComprasAlerta` then navigate; **X** → `/ok` (already). (b) `compras.faltantes`: `dismissible={true}`; **X**/`onDismiss` → `handleSnoozeComprasAlerta` (same as Posponer, ~1h); **Ver** → navigate only (no `/ok`, no snooze). Permanent faltantes clear stays resolve path. (`alert-open`, `alert-ver-dismiss`, `alert-faltantes-x-snooze`)
- [x] 3.5 In `frontend/src/components/compras/TabRecepcionDeposito.jsx` split `pedidos_documento` on `;` (strip, drop empty); chip each stored string — no `Number()`. Change `incluirCC` from `useState(false)` to `useState(true)`. (`dep-chips`, `dep-cc-default`)
- [x] 3.6 REMOVED (wrong item-4 checkbox interpretation) — do not change ModalPedidoDetalle cargada binding for this change.
- [x] 3.7 Amend `frontend/src/novedades/2026-09-23-compras-pipeline-ux.md` (same entry as merged stack — no new file): document Incluir CC **defaults on**; Pedidos list default omits cancelados (Cancelado still selectable). Do not add a separate novedad for bugfixes. (`dep-cc-default`, `ped-filter`)

## Phase 4: Tests

- [x] 4.1 `backend/tests/unit/test_oc_match_doc_refs.py` + `backend/tests/unit/test_oc_match_pipeline.py`: `nc`/`nd` aliases; quote `00184465`. (`oc-extract`)
- [x] 4.2 `backend/tests/integration/test_oc_match_worker.py`: NC/ND no columns, no stamp, no factura row; factura seeds `cargada=false`. (`oc-route`, `fact-nc`)
- [x] 4.3 `backend/tests/integration/test_compras_endpoints.py`: default `excluir_estado=cancelado`; explicit `cancelado` + logistic estados. (`ped-filter`)
- [x] 4.4 `frontend/src/components/compras/TabPedidosCompra.test.jsx` + `frontend/src/components/AppLayout.comprasBanners.test.jsx`: default filter; Ver/banner nonce; close/tab no sticky reopen; inbound opens once; **factura Ver+/ok permanent**; **faltantes X → snooze** (dismissible); faltantes Ver no `/ok`/snooze. Update/replace old “faltantes not dismissible” tests. (`ped-filter`, `ped-query`, `alert-open`, `alert-ver-dismiss`, `alert-faltantes-x-snooze`)
- [x] 4.5 `frontend/src/components/compras/TabRecepcionDeposito.test.jsx`: chips `00184465` and `0012`/`PED-08`; Incluir CC defaults checked and Por recibir first fetch includes `en_cuenta_corriente`. (`dep-chips`, `dep-cc-default`)
