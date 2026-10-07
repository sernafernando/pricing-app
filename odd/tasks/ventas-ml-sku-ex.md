# Ventas ML: SKU actual + "ex SKU" y búsqueda por SKU numérico

## Objetivo
Ventas ML muestra SIEMPRE el SKU ACTUAL de MercadoLibre. Si cambió desde la venta,
se muestra también el SKU viejo como "ex <SKU viejo>" (fila y detalle). La
búsqueda encuentra la venta por cualquiera de los dos SKU.

## Problema
1. `apply_search` (ml_sales_query/search.py): texto todo dígitos busca SOLO order_id/pack_id y
   sale temprano -> un SKU numérico (o EAN) nunca se encuentra por SKU.
2. `_upsert_item_row` (ON CONFLICT DO UPDATE) pisa `ml_order_items_ops.seller_sku` con el
   valor actual en cada re-ingesta: se pierde el SKU con el que se vendió.

## Alcance
- Migración: columna nullable `seller_sku_vendido` + índice (igual que `ix_ml_order_items_ops_seller_sku`) + backfill `= seller_sku`.
- Ingesta: INSERT guarda el SKU entrante; en UPDATE nunca se pisa (COALESCE del primero conocido).
- Búsqueda: dígitos = order_id/pack_id OR order_id IN (items con seller_sku == texto OR seller_sku_vendido == texto), match EXACTO, también para valores fuera de BIGINT; texto libre suma seller_sku_vendido al ILIKE; rama MLA igual.
- API: `seller_sku_anterior: Optional[str]` en `OrderItemOpsSummary` e `ItemDesgloseLineSummary`; null si igual o desconocido.
- Frontend: "ex <SKU>" discreto en `ProductCell.jsx` y `SaleContextSections.jsx`.
- Novedades en la misma PR.
- Fuera de alcance: recuperar historia ya pisada (ver Hallazgos).

## Constraints / TDD
- TDD: strict (instrucción global). Runners: `pytest` (backend/.venv), `pnpm test` (vitest).
- Pre-push hook corre GGA; se arreglan todas las observaciones. No PR.

## Tareas
- [x] T1 Búsqueda por SKU numérico/EAN exacto (RED -> GREEN) + fuera de BIGINT
- [x] T2 Migración + modelo `seller_sku_vendido` (cabeza única de alembic)
- [x] T3 Ingesta conserva el SKU vendido en re-ingesta (RED -> GREEN, Postgres)
- [x] T4 Búsqueda de texto libre incluye `seller_sku_vendido`
- [x] T5 API `seller_sku_anterior` (RED -> GREEN)
- [x] T6 Frontend "ex SKU" fila + detalle (vitest RED -> GREEN)
- [x] T7 Novedad + lint + push

## Hallazgos
- Recuperación de SKUs ya pisados: NO es posible. `raw_item` (JSONB) se pisa en el mismo upsert; `ml_order_item_costos` no guarda SKU (solo producto_item_id de ERP); `ml_cancelled_orders.items` solo existe para canceladas y no hay tabla de payload crudo histórico de ítems. El backfill copia el SKU actual.

## Checks
`pytest` de tests/services/ml_sales_query, tests/services/ml_orders_ingestion, router ml_ventas_ops; vitest ventasMl; ruff check/format; `pnpm run lint`, `pnpm run lint:css`.

## Progreso / evidencia
- T1 RED: 3 tests fallan (SKU numérico, unión, EAN > BIGINT) -> GREEN 20 passed (test_search.py).
- T2/T3 RED: 5 tests Postgres fallan (seller_sku_vendido None) -> GREEN: tests/services/ml_orders_ingestion 465 passed; migración: 5 passed, mutación del backfill la rompe (2 failed).

## Mirror Engram
topic `odd/ventas-ml-sku-ex/tasks`, proyecto pricing-app.
- T4 RED 3 failed -> GREEN ml_sales_query 140 passed. T5 RED KeyError seller_sku_anterior -> GREEN; related suites 1167 passed. T6 RED 3 failed (vitest) -> GREEN ventasMl 146 passed; novedad 13 passed; pnpm lint 0 errors (2 preexisting warnings), lint:css clean.
