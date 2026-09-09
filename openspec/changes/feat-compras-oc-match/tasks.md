# Tasks: feat-compras-oc-match

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900–1400 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 → PR 4 |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Models, Alembic, settings, MIME, empresa, template | PR 1 (tracker) | `pytest test_oc_match_mime.py test_compras_empresa_oc_map.py` | N/A — hook unwired | models + Alembic + MIME |
| 2 | Hook + enqueue + list/retry | PR 2 (PR 1) | `pytest test_oc_match_enqueue.py test_oc_match_reclaim.py` | PDF `queued`; XLSX `skipped` | hook + enqueue + list/retry |
| 3 | Worker extract/match/excel/acta | PR 3 (PR 2) | `pytest test_oc_match_pipeline.py test_oc_match_worker.py` | Mocked-pool golden + xlsx | `services/oc_match/*` + excel GET |
| 4 | Tab + poll + retry | PR 4 (PR 3) | `pnpm test -- TabOcMatch useOcMatch` | `?tab=oc-match`; poll stops | tab + hook + TABS |

## Phase 1: Foundations (PR 1)

- [x] 1.1 Alembic head at apply; not `compras_039`.
- [x] 1.2 Add `backend/app/models/oc_match_job.py`; export in `backend/app/models/__init__.py`.
- [x] 1.3 Alembic jobs/renglones: unique `(pedido_id, attachment_id)`, status CHECK, indexes.
- [x] 1.4 Settings in `backend/app/core/config.py` (Gemini keys, `COMPRAS_OC_MATCH_DIR`, `COMPRAS_OC_MATCH_ENABLED`); `google-genai>=1.0.0` in `backend/requirements.txt`.
- [x] 1.5 Add `backend/app/core/compras_empresa_oc_map.py` `{1:PASTORIZA,2:GRUPO GAUSS}`.
- [x] 1.6 MIME in `backend/app/services/oc_match/mime.py`; keep Office valid in `backend/app/services/compras_adjuntos_service.py`.
- [x] 1.7 Vendor GBP xlsx at `backend/app/services/oc_match/templates/`.
- [x] 1.8 Tests `backend/tests/unit/test_oc_match_mime.py` + `backend/tests/unit/test_compras_empresa_oc_map.py`: PDF/image vs Office; map 1/2; zero Gemini; hook unwired.

## Phase 2: Trigger (PR 2)

- [ ] 2.1 Add `backend/app/schemas/oc_match.py` Pydantic v2 `from_attributes=True`.
- [ ] 2.2 Enqueue/claim/reuse in `backend/app/services/oc_match/enqueue.py`.
- [ ] 2.3 After `_commit_or_rollback` in `subir_adjunto_pedido` (`backend/app/routers/administracion_compras.py`): MIME gate; `add_task` only PDF/image.
- [ ] 2.4 GET list/detail + POST retry + 15-min reclaim in `backend/app/routers/administracion_compras.py` (`ver`/`gestionar`; no deposito ACL).
- [ ] 2.5 Tests `backend/tests/integration/test_oc_match_enqueue.py` + `backend/tests/unit/test_oc_match_reclaim.py`: create/OP/NC no job; PDF queued; XLSX skipped; reuse; stale running→error; 403; no mail.

## Phase 3: Pipeline (PR 3)

- [ ] 3.1 Port extract + 3-key pool to `backend/app/services/oc_match/` (no Session during Gemini).
- [ ] 3.2 Maestro `tb_item` ⨝ brand/cat; skip fabricante exact; EAN=`item_code`; not `productos_erp`.
- [ ] 3.3 Two-session worker via `get_background_db()`: claim `queued→running`; persist renglones+acta+xlsx.
- [ ] 3.4 USD no TC → `error`+acta (never empty xlsx success); GET excel `FileResponse`.
- [ ] 3.5 Tests `backend/tests/unit/test_oc_match_pipeline.py` + `backend/tests/integration/test_oc_match_worker.py`: mocked-pool golden SoT; skip-fab; unmatched packs in acta; USD-no-TC; no mail.

## Phase 4: UI (PR 4)

- [ ] 4.1 Add `frontend/src/hooks/useOcMatch.js`: list/detail/retry/excel; poll 3s while `queued|running`.
- [ ] 4.2 Add `frontend/src/components/compras/TabOcMatch.jsx` + `frontend/src/components/compras/TabOcMatch.module.css`: renglones/acta/download; retry iff `gestionar`.
- [ ] 4.3 Register `TABS` `id: oc-match` in `frontend/src/pages/AdministracionCompras.jsx` (`administracion.ver_ordenes_compra`).
- [ ] 4.4 Tests `frontend/src/components/compras/TabOcMatch.test.jsx` + `frontend/src/hooks/useOcMatch.test.js`: tab hidden without view; retry hidden view-only; poll stops on `done|error|skipped`.
