# ml-items-bulk

## Objective
Migrate every pricing-app multiget against MercadoLibre from the deprecated `GET /items?ids=` to `GET /items/bulk?ids=` before 2026-10-25 (source: https://developers.mercadolibre.com.ar/es_ar/items-y-busquedas). No `/users?ids=` caller exists in backend/app or frontend/src.

## Doc facts
- `/items/bulk`: `code` -> `status_code`, `id` at element root, attribute selection needs `body.` prefix.
- The doc has NO `/items/bulk` response example; fixtures come from the real capture `backend/tests/fixtures/ml/items_bulk_capture_20261006.json` (production, 2026-10-06, read-only).
- Max ids per call: 20 (deprecated multiget limit; bulk limit undocumented, 20 kept).

## Observed shapes (capture)
1. bulk: `[{"id","status_code":200,"body":{...}}, {"id":"MLA1","status_code":404,"error":{...}}]` (404 has no body).
2. bulk + attributes: `[{"body":{"id","status","available_quantity"}}, {}]` (no root id/status_code; unknown id = `{}`).
3. legacy: `[{"code":200|404,"body":{...}}]` (404 body carries error fields, including an `id`).
Parser handles all three (legacy stays live until the bridge PR deploys).

## Callers
- `backend/app/services/ml_api_client.py` `get_items_batch` (+ `get_user_items` caller)
- `backend/app/scripts/sync_ml_publications.py`, `sync_ml_publications_full.py`, `sync_ml_publications_incremental.py`
- NOT affected: `ml_webhook_client.get_items_batch` fetches one item per call via `/api/ml/preview?resource=/items/{id}` (no multiget).

## Deploy order
This pricing PR FIRST (tolerant parser, both shapes), THEN the ml-webhook bridge PR (forwards old-form requests to bulk, returns the bulk shape as-is).

## Constraints
TDD strict (RED first). Conventional commits, no AI attribution. ruff format app/ tests/.

## Tasks
- [ ] T1 shared parser `app/services/ml_multiget.py` + tests (RED/GREEN)
- [ ] T2 `ml_api_client.get_items_batch` -> `/items/bulk` + tests
- [ ] T3 three sync scripts -> `/items/bulk` + parser + tests
- [ ] T4 full verification + push (GGA)

## Route
Inline: small, understood, 4 callers (direct inline, delegation triggers not fired: <=3 files read per decision).

## Evidence
(filled as tasks close)
