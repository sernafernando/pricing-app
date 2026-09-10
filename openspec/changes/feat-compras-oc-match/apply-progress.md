# Apply Progress: feat-compras-oc-match

**Change**: feat-compras-oc-match
**Mode**: Standard
**Slice**: Phase 1 / PR 1 Foundations (tasks 1.1–1.8)
**Branch**: feat/compras-oc-match-01-foundations
**Chain**: feature-branch-chain (PR 1 targets feature/admin-ocs tracker)
**Hook**: UNWIRED — zero Gemini calls

## Completed Tasks

- [x] 1.1 Alembic head at apply; not `compras_039`.
- [x] 1.2 Add `backend/app/models/oc_match_job.py`; export in `backend/app/models/__init__.py`.
- [x] 1.3 Alembic jobs/renglones: unique `(pedido_id, attachment_id)`, status CHECK, indexes.
- [x] 1.4 Settings in `backend/app/core/config.py` (Gemini keys, `COMPRAS_OC_MATCH_DIR`, `COMPRAS_OC_MATCH_ENABLED`); `google-genai>=1.0.0` in `backend/requirements.txt`.
- [x] 1.5 Add `backend/app/core/compras_empresa_oc_map.py` `{1:PASTORIZA,2:GRUPO GAUSS}`.
- [x] 1.6 MIME in `backend/app/services/oc_match/mime.py`; keep Office valid in `backend/app/services/compras_adjuntos_service.py`.
- [x] 1.7 Vendor GBP xlsx at `backend/app/services/oc_match/templates/`.
- [x] 1.8 Tests `backend/tests/unit/test_oc_match_mime.py` + `backend/tests/unit/test_compras_empresa_oc_map.py`: PDF/image vs Office; map 1/2; zero Gemini; hook unwired.

## Work Unit Evidence (Phase 1)

| Evidence | Value |
|---|---|
| Focused test command and exact result | `pytest tests/unit/test_oc_match_mime.py tests/unit/test_compras_empresa_oc_map.py -q` → **22 passed** in 0.09s |
| Runtime harness command/scenario and exact result | N/A — hook unwired; no enqueue/Gemini/runtime boundary in this slice |
| Rollback boundary | models (`oc_match_job.py` + `__init__.py` export), Alembic `compras_040_oc_match` (`down_revision=20260909_activity_cursor`), MIME package, empresa map, settings/dep, vendored xlsx, Phase 1 unit tests. Revert does not remove Phase 2–4 work (none landed). |

## Implementation notes

- Alembic graph at apply had a **single head**: `20260909_activity_cursor` (revises `20260909_seed_ml_bridge`). New revision `compras_040_oc_match` uses that head. Confirmed `compras_039` is **not** the head (`20260811_porcentaje_tarjeta_tn` already revises it).
- Models: `OcMatchJob` + `OcMatchRenglon` in one file; unique `(pedido_id, attachment_id)`; status CHECK; indexes on status, pedido_id, started_at; renglones CASCADE + extract/match columns.
- Settings added next to `COMPRAS_UPLOADS_DIR`. `google-genai>=1.0.0` added; **not imported** in Phase 1.
- MIME: magic-first then suffix. OOXML/OLE2 → `office`. PDF/JPEG/PNG/WEBP → `gemini`. `compras_adjuntos_service` still accepts Office.
- Template: copied bytes-identical from Automations `Orden de Compra - Carga Masiva de Artículos (1).xlsx` → `backend/app/services/oc_match/templates/carga_masiva_articulos.xlsx` (filename shortened; see templates/README.md).

## Deviations from Design

None — implementation matches design.md for Phase 1.

## Remaining Tasks

Phase 2–4 (2.1–4.4) not assigned this batch.

## Workload / PR Boundary

- Mode: chained PR slice
- Current work unit: PR 1 Foundations
- Boundary: models + Alembic + settings + MIME + empresa map + vendored xlsx + unit tests; hook stays unwired
- Estimated review budget impact: authored Python/docs likely near or over 400 lines; binary xlsx excluded from authored count. Report honestly if `git diff --stat` exceeds budget — do not golf.
