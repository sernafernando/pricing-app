# publicaciones-repair

Objective: Persist ML shipping fields + fix seller_sku on publication snapshots (PR1), then repair envío (PR2) and SKU (PR3) jobs hooked after `sync_ml_publications_full`.
Branch: `feat/publicaciones-repair` (base `upstream/main`). Delivery: `auto-chain` / `stacked-to-main` (PRs ≤400 lines to `sernafernando/pricing-app:main`). Runner: `pytest` under `backend/`.

## Specs

- S1: Extender el sync que YA trae el item de ML: `sync_ml_publications_full` (y el path de snapshots / incremental si aplica el mismo writer). Persistir en Pricing (preferencia: `ml_publication_snapshots`) estos campos de `shipping`: `mode`, `logistic_type`, `local_pick_up`, `free_shipping`, `store_pick_up`, `tags` (shipping tags; p.ej. lista/JSON). Migración Alembic + actualizar writers del sync. Sin crontab nuevo.
- S2: Bug: `seller_sku` llega null en muchos snapshots aunque ML tiene SELLER_SKU. Ejemplo: MLA905437269 tiene SKU `840006603337` en ML y en `publicaciones_ml.codigo`, pero snapshots recientes tienen `seller_sku` null. Arreglar el parseo/persistencia. (Root cause: writers leen `value_id`; ML deja `value_id` null y el SKU vive en `value_name` — mismo patrón que `attribute_value_name` en `ml_publications.mappers`.)
- S3 (PR2, later): Job repair envíos — universo `publicaciones_ml`; drift desde DB vs constantes objetivo; ML solo para corregir; tracker `publicacion_repair_run` / `publicacion_repair_event`; enganche al final de `sync_ml_publications_full`.
- S4 (PR3, later): Job repair SKUs — misma cáscara; `job_type=sku`; detectar desde DB; solo escribir en ML lo roto. Contraste: `seller_sku` (snapshot/ML) vs **código ERP del vínculo** de ese MLA; universo **solo publicaciones efectivamente vinculadas** (`publicaciones_ml` / link ERP). PR1 solo persiste bien el SKU leído de ML — no repara.

Out of scope unless asked: UI nueva, crons nuevos, unificar envíos+SKU en un mega-job, tocar `auditoria` de precios.

## Tasks

- T1 — S1-S2 — route: inline — status: done — commit: pending — Persist shipping columns on `ml_publication_snapshots` + fix seller_sku parse in sync writers + migration + focused tests. GREEN: `tests/scripts/test_sync_ml_publications_snapshot_fields.py` + bulk (8 passed).
- T2 — S3 — route: inline — status: pending — Envios repair job + tracker tables + hook.
- T3 — S4 — route: inline — status: pending — SKU repair job on same tracker.

## Log

- L1: Gabe brief (change agent handoff): PR1 persist shipping + fix SKU sync; PR2 envio repair; PR3 sku repair; chained sequential; no Cursor/AI attribution; Metabase for DB reads.
- L2: Exploration: `extraer_datos_publicacion` / legacy sync use `attr.get("value_id")` for SELLER_SKU; fixture and mappers docstring confirm value lives in `value_name`. Metabase: MLA905437269 recent snapshots have `seller_sku` null. Snapshot table has no shipping columns yet. Alembic head: `20261217_drop_sell_in_compras_pedido_compra_id`.
- L3: Live ML confirms mixed shapes — some items have value_id=value_name (snap OK), others value_id null (snap null). ~9.7k snap_null with ml_items SKU present (last day).
- L4: T1 implemented — model + alembic `20261218_ml_pub_snapshots_shipping`; writers use `attribute_value_name` + shipping fields; legacy sync reuses full helpers; README updated. Risk: item 1 (migration).
- L5: Gabe: continuar bugfix (PR1 persist); el PR posterior de repair SKU debe contrastar vs código ERP del vínculo MLA, solo vinculadas. Authorized `--no-verify` for GGA (Claude CLI missing).
