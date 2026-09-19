# Design: feat-compras-oc-match

## Technical Approach

Port Automations `extractor/`, `matching/`, `excel/`, `host/acta.py` into Pricing. After `subir_adjunto_pedido` commits, MIME-gate + persist job; `BackgroundTasks` runs extract → match → excel → persist via `get_background_db()` (tickets/triage). DB is SoT. Mail OFF. Specs: jobs, pipeline, ui.

```
POST /pedidos/{id}/adjuntos → commit
  MIME (magic+suffix): Office → job skipped, no Gemini
                       PDF/image → queued + add_task(run_oc_match)
  worker: extract (3-key pool) → match(tb_item) → xlsx disk → renglones+acta
  Tab polls GET until done|error|skipped
```

## Architecture Decisions

| Topic | Options / tradeoff | Decision |
|-------|--------------------|----------|
| Async | Celery vs job table | **Job table + poll** (locked). List/detail persist `running`>15m as retryable `error`. |
| Hook | Service flush vs router after `_commit_or_rollback` | **Router only** on pedido adjunto. OP/NC unchanged. |
| Sessions | One long session vs split | **Two short sessions**: claim `queued→running`; close; Gemini/excel with **no** Session (`statement_timeout=60s`); persist. |
| Empresa | Reuse ERP map vs new | **New** `compras_empresa_oc_map.py` `{1:PASTORIZA,2:GRUPO GAUSS}`. Unmapped → `error`+acta, no Gemini. |
| Maestro | `productos_erp` vs `tb_item` | **`tb_item` ⨝ brand/cat/subcat**. `ean=item_code`, `item_id=str(item_id)`, `fabricante=""`. Skip `match_fabricante_exacto`. Keep `sin_combos_internos`. |
| Excel | Rebuild vs vendor | **Vendor** Automations GBP xlsx at `services/oc_match/templates/`. Sibling dir `COMPRAS_OC_MATCH_DIR`. |
| Keys | raw getenv vs Settings | **Settings**. Never log keys. |
| Rollback | revert vs flag | `COMPRAS_OC_MATCH_ENABLED` default true. |
| List ACL | include deposito | **`ver_ordenes_compra` only**. |

USD without TC (`RechazoExcel`): `error`+acta; never treat empty xlsx as success.

## Data Model

Alembic `compras_040_oc_match` (or dated) on **current head at apply** — not `compras_039` (later heads exist).

**`compras_oc_match_jobs`**: `id`; FKs `pedido_id`→`pedidos_compra`, `attachment_id`→`compras_adjuntos` RESTRICT; `status` CHECK `queued|running|done|error|skipped`; `error_message`; `acta`; `excel_rel_path` (rel. to OC dir); `started_at`/`finished_at`; timestamps. Unique `(pedido_id, attachment_id)`. Indexes: status, pedido_id, started_at.

**`compras_oc_match_renglones`**: `job_id` CASCADE; `indice`; extract fields; `match_estado` `ok|no_hallado|omitido`; `item_id`, `ean`, `confianza`, `motivo`.

Idempotency: unique hit + `done|running` → reuse, no second `add_task`. New adjunto → new job. Retry (`gestionar`): `error` only → `queued` + `add_task`. Claim: `UPDATE … running WHERE id=? AND queued` (0 rows → no-op).

## API Surface

Prefix `/administracion/compras`. Pydantic v2 `from_attributes=True`. No public enqueue. No mail.

| Method | Path | Permiso |
|--------|------|---------|
| GET | `/oc-match/jobs?status=&page=&page_size=50` | `ver_ordenes_compra` |
| GET | `/oc-match/jobs/{id}` | `ver_ordenes_compra` |
| POST | `/oc-match/jobs/{id}/retry` | `gestionar_ordenes_compra` |
| GET | `/oc-match/jobs/{id}/excel` | `ver_ordenes_compra` |

List: jobs for accessible pedidos (pedidos ACL **without** deposito-only branch). Filter `queued|running|done|error`; `skipped` optional. Reclaim before serialize. Retry 403 view-only / 409 not retryable. Excel: `FileResponse` like `descargar_adjunto`.

## Frontend Tab

`TABS` `id: oc-match`, permiso `ver_ordenes_compra`, `TabOcMatch` + CSS Module (CF/Tesla) + `useOcMatch` (Cheques wrap). Poll **3s** while `queued|running`; stop on terminal/unmount. Retry iff `gestionar` + retryable `error`. `?tab=` works; job-id query later.

## Env Vars

| Var | Default |
|-----|---------|
| `GEMINI_API_KEY` (+ `_2`, `_3`) | Gabe → Chicho `.env` |
| `GEMINI_MODEL` | `gemini-3.6-flash` |
| `COMPRAS_OC_MATCH_DIR` | `uploads/compras_oc` |
| `COMPRAS_OC_MATCH_ENABLED` | `true` |

Missing keys → job `error`+acta, never fail the 201. Dep: `google-genai>=1.0.0`.

## File Changes

Create: `models/oc_match_job.py`, `schemas/oc_match.py`, `core/compras_empresa_oc_map.py`, `services/oc_match/*` (mime, enqueue, worker, pool, extract, maestro, match, excel, acta, template), Alembic, `TabOcMatch.*`, `hooks/useOcMatch.js`. Modify: `config.py`, `requirements.txt`, `compras_adjuntos_service.py` (classify, do not reject Office), `administracion_compras.py` (hook + 4 endpoints), `models/__init__.py`, `AdministracionCompras.jsx`. Do **not** port mail, Sheet, Drive, Coolify API, Playwright.

## Testing Strategy

Unit: MIME, empresa map, skip-fab, USD-no-TC, reclaim, unique reuse — no Gemini. Integration: spy `BackgroundTasks` (PDF queued; XLSX skipped; create/OP/NC no job); mocked-pool golden → renglones+acta+xlsx. FE: tab/retry gates; poll stops (fake timers).

## Threat Matrix

N/A — no routing/shell/subprocess/VCS/PR/executable-file boundary. Gemini is HTTPS SDK; Excel is in-process `openpyxl`.

## PR Slices (chained, 400-line budget)

| Slice | Scope | Done when |
|-------|--------|-----------|
| **1 Foundations** | Models, Alembic, settings, MIME, empresa map, xlsx, dep | Units green; **zero** Gemini; hook unwired |
| **2 Trigger** | Post-commit hook + enqueue + skip + list/detail/retry | PDF `queued`; XLSX `skipped`; create/OP/NC no job |
| **3 Pipeline** | Port extract/match/excel/acta; two-session worker; download | Golden SoT + xlsx; USD no TC → `error` |
| **4 UI** | Tab + hook + poll | Operator works without mail |

Each PR targets the previous branch. Coolify cutover is ops.

## Migration / Rollout

Additive tables. Dual-run until Gabe stops Coolify mail. Rollback: flag false; jobs read-only; delete xlsx; Alembic downgrade; remove tab.

## Risks / Mitigations

| Risk | Mitigation |
|------|------------|
| Worker death | 15-min reclaim persist + retry |
| No fabricante exact | Acta flags unmatched (locked) |
| Gemini 429/503 | 3-key pool; never in upload request |
| N files = N Gemini | Sequential panel POSTs; accept quota |
| Session timeout | No Session during Gemini |
| Oversized PR | Four chained slices |

## Open Questions

None. Poll 3s is a default.
