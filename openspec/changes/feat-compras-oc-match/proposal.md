# Proposal: feat-compras-oc-match

## Intent

Port Automations OC into Pricing Compras. Trigger: pedido adjunto upload, not create. Pricing DB is SoT. Mail OFF; Coolify until Gabe cutover.

## Scope

### In Scope
- Hook after `subir_adjunto_pedido` commit; enqueue PDF/JPG/JPEG/PNG/WEBP only (Office adjunto allowed, no Gemini).
- Job + lines + acta in DB; Excel on disk (`COMPRAS_UPLOADS_DIR` sibling).
- Port `extractor/`, `matching/` (`tb_item` adapter), `excel/`, `host/acta.py`; 3-key Gemini pool.
- Compras tab (Cheques pattern) + poll; `BackgroundTasks` + job table (no Celery).

### Out of Scope
- Mail, Sheet, Drive, Coolify API, Playwright GBP import.
- Trigger on pedido create or OP/NC adjuntos.
- New permiso, fabricante GBP sync, Celery, Coolify shutdown (ops).

## Capabilities

### New Capabilities
- `compras-oc-match-jobs`: enqueue, MIME gate, idempotency, reclaim, list/retry/download.
- `compras-oc-match-pipeline`: Gemini extract, `tb_item` match, Excel, acta.
- `compras-oc-match-ui`: tab, poll, renglones/acta, download.

### Modified Capabilities
- None (no compras spec in `openspec/specs/`; adjunto upload unchanged).

## Approach

Upload → commit → MIME gate → job `queued` → `BackgroundTasks` (own session): extract → match → excel → persist. Tab polls until `done|error|skipped`.

**Closed explore points**
- **Fabricante:** skip exact-fab; EAN=`item_code` + Gemini (`tb_item` has no manufacturer code). Later GBP enrich. Acta flags unmatched (packs/colors).
- **Permiso:** view `administracion.ver_ordenes_compra`; retry `administracion.gestionar_ordenes_compra` (Pedidos; no new seed).
- **Idempotency:** unique `(pedido_id, attachment_id)`. New file = new job; same file `done|running` → reuse/skip.
- **Reclaim:** list/detail marks `running` >15 min as retryable `error` (worker death).
- **Excel:** vendor Automations `docs/ejemplos-proformas/Orden de Compra - Carga Masiva de Artículos (1).xlsx`.
- **List:** jobs for accessible pedidos; filter `queued|running|done|error` (+`skipped`); deep-link later.

Empresa `1→PASTORIZA`, `2→GRUPO GAUSS`. Maestro: `tb_item` ⨝ brand/cat; not `productos_erp`.

**PR slices:** (1) models/Alembic/settings/MIME/empresa (2) upload hook (3) pipeline (4) tab.

## Affected Areas

- Modified: `administracion_compras.py`, `compras_adjuntos_service.py`, `core/config.py`, `requirements.txt`, `AdministracionCompras.jsx`.
- New: Alembic job/renglones/acta; `services/oc_match/`; `TabOcMatch.*`.

## Risks

- Worker death (High): 15-min reclaim + retry.
- No fabricante exact (High): acta unmatched; later GBP field.
- Gemini quota/503 (Med): 3-key pool; never in upload request.
- Dual-run mail + tab (Med): Pricing mail OFF; Gabe cuts Coolify after ship.
- Oversized PRs (High): four chained slices.

## Rollback Plan

Skip the upload hook. Jobs read-only; delete Excel files; downgrade Alembic; remove tab. Coolify mail unchanged.

## Dependencies

- Gabe: 3 Gemini keys; Chicho loads `.env`. Vendored GBP xlsx. `google-genai`; `openpyxl` present.

## Success Criteria

- [ ] Create pedido → no job; PDF/image → job; Office → `skipped`/`error`, no Gemini.
- [ ] Golden PDF → renglones + acta + xlsx; tab + download work.
- [ ] Same adjunto reuses `done|running`; new adjunto = new job.
- [ ] `running` >15 min → retryable `error` on list/detail.
- [ ] Pricing sends no mail.
