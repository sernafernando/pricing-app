# publicaciones-repair

Objective: Persist ML shipping fields + fix seller_sku on publication snapshots (PR1), then repair envío (PR2) and SKU (PR3) as **conditional ticks** (ml_items drift × linked pubs), not hooked on the publications sync cron.
Branch: stacked `feat/publicaciones-repair` → `-02-tracker` → `-02-envio` → `-03-sku`. Delivery: `auto-chain` / `stacked-to-main`. Runner: `pytest` under `backend/`.

## Specs

- S1: Persist shipping on `ml_publication_snapshots` via sync writers. Migración Alembic (re-parent to main head before merge).
- S2: `seller_sku` from `value_name` (not `value_id`). Do **not** derive snapshot `item_id` from free-text SKU/EAN. Never use `str.isdigit()` for int conversion of SKUs.
- S3: Envío repair — universo `publicaciones_ml` activas ∩ `ml_items` (status active/paused, not Full); drift vs política ME2/local_pick_up/colecta-Flex; never write free_shipping/tags/store_pick_up. Trigger: background tick (free_shipping-style), **not** end of `sync_ml_publications_full`. Tracker + short sessions + write_log + refresh + attempt cap + kill switches.
- S4: SKU repair — mismas vinculadas; drift `ml_items.seller_sku` ≠ `ProductoERP.codigo`; ERP codigo wins. Same tick shell; honor `ML_PUB_KILL_SWITCH` + `ML_ITEM_DATA_WRITE_ENABLED`.

Out of scope unless asked: UI nueva, PUTs inside RefreshHandler, unificar envío+SKU en un mega-job, tocar `auditoria` de precios.

## Tasks

- T1 — S1-S2 — route: inline — status: done — #1985 tip `2dec315b6`.
- T2 — S3 — route: inline — status: done — #1987 tip envio tick + detached/cap.
- T3 — S4 — route: inline — status: in_progress — #1988 SKU tick + kill switch.

## Log

- L8: Gabe+Chicho: repair on tick = ml_items drift × linked pubs (not sync_full).
- L9: Fernando follow-ups addressed on stack tips.
