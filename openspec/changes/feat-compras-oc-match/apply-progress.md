# Apply Progress: feat-compras-oc-match

**Change**: feat-compras-oc-match
**Mode**: Standard
**Slice**: Phase 2 / PR 2 Trigger (tasks 2.1–2.5); Phase 1 already landed
**Branch**: feat/compras-oc-match-02-trigger
**Chain**: feature-branch-chain (PR 2 targets PR 1 `feat/compras-oc-match-01-foundations`)
**Hook**: WIRED after `subir_adjunto_pedido` commit; Gemini still unwired (`process_oc_match_job` no-op, job stays `queued`)
**Workload**: size:exception — authored add+del ~949 vs max_changed_lines=500; cannot split tests from hook/enqueue/list/retry without leaving the work unit unverified

## Completed Tasks

- [x] 1.1 Alembic head at apply; not `compras_039`.
- [x] 1.2 Add `backend/app/models/oc_match_job.py`; export in `backend/app/models/__init__.py`.
- [x] 1.3 Alembic jobs/renglones: unique `(pedido_id, attachment_id)`, status CHECK, indexes.
- [x] 1.4 Settings in `backend/app/core/config.py` (Gemini keys, `COMPRAS_OC_MATCH_DIR`, `COMPRAS_OC_MATCH_ENABLED`); `google-genai>=1.0.0` in `backend/requirements.txt`.
- [x] 1.5 Add `backend/app/core/compras_empresa_oc_map.py` `{1:PASTORIZA,2:GRUPO GAUSS}`.
- [x] 1.6 MIME in `backend/app/services/oc_match/mime.py`; keep Office valid in `backend/app/services/compras_adjuntos_service.py`.
- [x] 1.7 Vendor GBP xlsx at `backend/app/services/oc_match/templates/`.
- [x] 1.8 Tests `backend/tests/unit/test_oc_match_mime.py` + `backend/tests/unit/test_compras_empresa_oc_map.py`: PDF/image vs Office; map 1/2; zero Gemini; hook unwired.
- [x] 2.1 Add `backend/app/schemas/oc_match.py` Pydantic v2 `from_attributes=True`.
- [x] 2.2 Enqueue/claim/reuse in `backend/app/services/oc_match/enqueue.py`.
- [x] 2.3 After `_commit_or_rollback` in `subir_adjunto_pedido` (`backend/app/routers/administracion_compras.py`): MIME gate; `add_task` only PDF/image.
- [x] 2.4 GET list/detail + POST retry + 15-min reclaim in `backend/app/routers/administracion_compras.py` (`ver`/`gestionar`; no deposito ACL).
- [x] 2.5 Tests `backend/tests/integration/test_oc_match_enqueue.py` + `backend/tests/unit/test_oc_match_reclaim.py`: create/OP/NC no job; PDF queued; XLSX skipped; reuse; stale running→error; 403; no mail.

## Work Unit Evidence (Phase 1)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/unit/test_oc_match_mime.py tests/unit/test_compras_empresa_oc_map.py -q` → **22 passed** in 0.09s |
| Runtime harness command/scenario and exact result | N/A — hook unwired; no enqueue/Gemini/runtime boundary in this slice |
| Rollback boundary | models (`oc_match_job.py` + `__init__.py` export), Alembic `compras_040_oc_match` (`down_revision=20260909_activity_cursor`), MIME package, empresa map, settings/dep, vendored xlsx, Phase 1 unit tests. Revert does not remove Phase 2–4 work. |

## Work Unit Evidence (Phase 2)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/unit/test_oc_match_mime.py tests/unit/test_compras_empresa_oc_map.py tests/unit/test_oc_match_reclaim.py tests/integration/test_oc_match_enqueue.py -q` → **39 passed** in 6.20s |
| Runtime harness command/scenario and exact result | FastAPI TestClient: PDF adjunto → job `queued` + `BackgroundTasks.add_task(process_oc_match_job)`; XLSX → `skipped` and no task; create/OP/NC adjunto → zero jobs; list reclaim `running`>15m → retryable `error`; stub worker does not call Gemini |
| Rollback boundary | `schemas/oc_match.py`, `services/oc_match/enqueue.py`, `services/oc_match/__init__.py` exports, hook + GET/POST in `administracion_compras.py`, Phase 2 tests. Revert does not remove Phase 1 foundations or Phase 3–4 work (none landed). |

## Implementation notes

- Phase 1 notes unchanged (Alembic head `20260909_activity_cursor`, MIME magic-first, empresa map 1/2).
- Phase 2 schemas: Pydantic v2 `ConfigDict(from_attributes=True)`; `retryable` computed on serialize (`status == error`).
- Enqueue: unique `(pedido_id, attachment_id)` reuse without second `add_task`; Gemini MIME → `queued`+schedule; Office/unknown → `skipped`. `process_oc_match_job` is a no-op (job stays `queued`) until Phase 3.
- Hook only on `subir_adjunto_pedido` after `_commit_or_rollback`; never fails the 201; `COMPRAS_OC_MATCH_ENABLED` kill switch. OP/NC upload paths unchanged.
- List/detail reclaim 15 min then serialize. Retry `gestionar` only; 409 if not `error`. Excel GET deferred to Phase 3.
- Mail OFF: enqueue/router hook do not call notificacion/mail.
- **Adjunto delete:** `eliminar_adjunto` calls `delete_jobs_for_attachment` first so RESTRICT FK on `attachment_id` does not 500 after PDF enqueue (regression from wiring the hook).

## Deviations from Design

None — implementation matches design.md for Phase 2. Gemini pipeline remains Phase 3. RESTRICT on attachment stays; app clears jobs before delete.

## Remaining Tasks

Phase 3–4 (3.1–4.4) not assigned this batch.

## Workload / PR Boundary

- Mode: chained PR slice with **size:exception**
- Current work unit: PR 2 Trigger
- Boundary: schemas + enqueue/claim/reclaim/retry + post-commit hook + list/detail/retry endpoints + unit/integration tests; Gemini stays unwired
- Estimated review budget impact: authored add+del ≈ **949** (tracked 198 + new files 751) exceeds 500. Tests cannot be dropped; hook+API+tests are one cohesive unit. Do not golf.
