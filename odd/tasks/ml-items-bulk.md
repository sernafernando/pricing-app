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
- [x] T1 shared parser `app/services/ml_multiget.py` + tests (RED/GREEN)
- [x] T2 `ml_api_client.get_items_batch` -> `/items/bulk` + tests
- [x] T3 three sync scripts -> `/items/bulk` + parser + tests
- [ ] T4 full verification + push (GGA)

## Route
Inline: small, understood, 4 callers (direct inline, delegation triggers not fired: <=3 files read per decision).

## Evidence
- T1+T2 commit 0214fd8f: RED = ModuleNotFoundError (parser) and `/items` != `/items/bulk` (client); GREEN 13 passed.
- T3: RED = 6 failed with scripts reverted; GREEN 6 passed (tests/scripts/test_sync_ml_publications_bulk.py).
- Targeted `-k "ml_api_client or ml_webhook_client or sync_ml_publications or productos_detail or multiget"`: 197 passed.
