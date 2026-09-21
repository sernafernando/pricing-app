# Tasks: feat-compras-oc-match-ops-ux

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 250–450 |
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
| 1 | `progress_phase`, 45m reclaim, `pedido_numero`, expand-below TabOcMatch | PR 1 | `pytest tests/unit/test_oc_match_reclaim.py tests/integration/test_oc_match_enqueue.py tests/integration/test_oc_match_worker.py` ; `pnpm test -- TabOcMatch.test` | N/A — poll stays `queued\|running`; no Gemini/pool change | Alembic `compras_041` + enqueue/worker/router/schema + TabOcMatch |

## Phase 1: Schema

- [x] 1.1 Create `backend/alembic/versions/compras_041_oc_match_progress_phase.py`: nullable `progress_phase` String(20); CHECK `ck_oc_match_jobs_progress_phase` (`NULL OR IN ('extracting','matching','excel')`). Do not alter `ck_oc_match_jobs_status`. No phase index. Set `down_revision` to unique `alembic heads` at merge (branch tip `compras_040_oc_match`; rehang if develop advanced). Downgrade drops column+CHECK.
- [x] 1.2 Add `progress_phase` + same CHECK on `backend/app/models/oc_match_job.py`.
- [x] 1.3 Add `progress_phase` and `pedido_numero` (`str | None`) to `OcMatchJobResponse` in `backend/app/schemas/oc_match.py` (Pydantic v2 `ConfigDict(from_attributes=True)`). Keep `pedido_id`.

## Phase 2: Reclaim

- [x] 2.1 In `backend/app/services/oc_match/enqueue.py` set `RECLAIM_AFTER = timedelta(minutes=45)` and `STALE_MESSAGE` for 45 minutes; keep `started_at` clock (not `updated_at`).
- [x] 2.2 Clear `progress_phase=None` in `queue_retry` and `reclaim_stale_running` in `backend/app/services/oc_match/enqueue.py`.
- [x] 2.3 Update `backend/tests/unit/test_oc_match_reclaim.py`: 46m → retryable `error` + new `STALE_MESSAGE`; 15m stays `running`; retry/reclaim clear phase.

## Phase 3: Worker

- [x] 3.1 Add `_write_progress_phase(job_id, phase)` in `backend/app/services/oc_match/worker.py`: short `get_background_db()`; set phase + `updated_at`; never `status`; wrap `with` in `except Exception` (log warning, fail-soft).
- [x] 3.2 In `backend/app/services/oc_match/worker.py` after claim closes: write `extracting` then extract; `matching` then match; `excel` then generar. No Session during Gemini. Do not call from `backend/app/services/oc_match/gemini_pool.py` (read-only).
- [x] 3.3 On `_persist` success in `backend/app/services/oc_match/worker.py`, set `progress_phase=None`.
- [x] 3.4 Update `backend/tests/integration/test_oc_match_worker.py`: spy extracting→matching→excel then null; helper raise still runs extract; persist null; status stays `running`.

## Phase 4: API

- [x] 4.1 Add `joinedload(OcMatchJob.pedido)` on `listar_oc_match_jobs` (even if `empresa_id` already joins `PedidoCompra`) and `_obtener_oc_match_job_o_404` (beside renglones) in `backend/app/routers/administracion_compras.py`.
- [x] 4.2 In `backend/app/routers/administracion_compras.py` inject `pedido_numero` via `model_copy` on list/detail/retry (`getattr(job.pedido, "numero", None)`); keep `pedido_id`; missing pedido → `null`, HTTP 200.
- [x] 4.3 Update `backend/tests/integration/test_oc_match_enqueue.py`: list/detail include `pedido_numero` + `pedido_id`; missing pedido → null 200; running exposes `progress_phase` with `status=running`.

## Phase 5: UI

- [x] 5.1 In `frontend/src/components/compras/TabOcMatch.jsx` show Pedido as `pedido_numero || '—'` (~160px); keep `pedido_id` in payload; badge “Procesando”; secondary Extrayendo / Matcheando / Excel. Do not change `frontend/src/hooks/useOcMatch.js` (read-only).
- [x] 5.2 Stacked expand-below: `.layout` single column in `frontend/src/components/compras/TabOcMatch.module.css`; remove `minmax(16rem, 24rem)` grid and 960px stack; reuse `detailBody`; render detail only when `selected`; no empty aside/modal; renglones full width.
- [x] 5.3 `.tdError` in `frontend/src/components/compras/TabOcMatch.module.css`: drop nowrap/ellipsis; `white-space: pre-wrap` + `-webkit-line-clamp: 3`; keep `title`. Shared DataTable CSS unchanged.
- [x] 5.4 Update `frontend/src/components/compras/TabOcMatch.test.jsx`: `OC-100` numero; Procesando+matching subtitle; expand-below not aside/modal; error `title` has full text. Leave `frontend/src/hooks/useOcMatch.test.js` (read-only).
