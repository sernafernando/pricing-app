# Métricas ML — tablero bursátil por producto y publicación

## Objetivo

Pantalla nueva "Métricas ML" con forma de tablero bursátil: cómo vende y cuánto
gana cada PRODUCTO en Mercado Libre, y qué PUBLICACIÓN (MLA) de ese producto
rinde mejor. Más el filtro de TIENDA, que también se agrega a Ventas ML.

Pedido del usuario (2026-10-01): mismos filtros que Ventas ML (fechas,
marca/subcategoría/PM, búsqueda), agrupar por producto o por publicación,
ventas 24h/3d/7d/15d/30d, última venta, ageing por producto Y por publicación,
markup actual comparado con períodos anteriores con mini gráfico de línea
("como si fuera la bolsa"), tendencia de ventas con mini gráfico, espacio para
el futuro sell-in/sell-out. "Que se apeguen al diseño."

## Diseño (fuente de verdad visual)

`docs/design/metricas-ml/tablero.png` + `tablero.html` (Stitch, aprobado por
el usuario). Cambios pedidos sobre ese diseño que Stitch no llegó a aplicar:
- Filtro "TIENDA:" al inicio de la primera franja de filtros: Todas, Gauss,
  TP-Link Oficial, Otras oficiales (con conteo), mismo estilo de chips.
- Montos SIEMPRE en una línea ("$" nunca solo en su renglón).
- Mín/Máx 90D y el chip "vs anterior" en una línea.
- Tabla con scroll horizontal dentro de la tarjeta y columna Producto fija a
  la izquierda, para que se vean Resultado, Rotación y Sell-in/Sell-out.

## Decisiones

- Conviven con el "Dashboard Métricas ML" viejo (tabla `ml_ventas_metricas`,
  otra fórmula de markup) por un tiempo; después esta queda como única. Ruta
  y nombre distintos; no se toca el viejo.
- Fuente de verdad del dinero: `ml_order_metrics` (Total Gauss, costo,
  markup = SUM(total_gauss)/SUM(costo_mercaderia), nunca promedio de %).
- Día de una venta = acreditación (MAX date_approved de pagos relevantes),
  igual que Ventas ML.
- Orden con varios productos: Total Gauss y costo de la orden se reparten
  entre sus ítems en proporción al costo congelado de cada ítem
  (`costo_unitario_ars × quantity`). Si la orden no tiene costo, va a
  "sin datos para calcular" y se cuenta aparte, como en Ventas ML.
- Tienda = `mlp_official_store_id` actual de la publicación (57997 Gauss,
  2645 TP-Link, 144 Forza/Verbatim, 191942 multimarca). Si una publicación
  cambió de tienda, su historial se mueve con ella (limitación aceptada).
- Estado de publicación (activa/pausada/cerrada) = último estado del ERP; la
  UI lo dice así (no es confiable en vivo, fix diferido al módulo
  Publicaciones ML).
- Tabla resumen diaria (producto × MLA × día de acreditación × tienda) con
  SUMAS (unidades, bruto, total_gauss, costo, órdenes, última venta), nunca
  porcentajes. Se actualiza en el mismo flujo del worker que recalcula las
  métricas de una venta (sin cron). Backfill por script.
- (T1, writer) Chips de tienda: una por tienda conocida (Gauss, TP-Link
  Oficial, Forza/Verbatim, Multimarca) + "Sin tienda", selección única como
  las otras filas de chips. El backend acepta CSV (`stores=57997,sin_tienda`)
  para el tablero. "Sin tienda" = el MLA no tiene ninguna fila de publicación
  con `mlp_official_store_id` no nulo. Un pack que toca dos tiendas cuenta en
  las dos chips (igual que un pack mixto en los facets de estado).
- (Usuario, 2026-10-01) Nombres: la pantalla NUEVA se llama "Métricas ML" en
  el menú y en el título, con badge "Nuevo" en el menú por ahora. El
  dashboard viejo (`pages/DashboardMetricasML.jsx`) pasa a llamarse
  "Métricas ML (anterior)" en menú y título — sólo etiqueta, misma ruta y
  código. La nueva tiene su propia ruta (`/metricas-ml`).

## Tareas

Ruta: delegated direct (writer único). TDD estricto.

- [x] T1 — Filtro de tienda en Ventas ML (BE `SalesFilter.stores` por EXISTS
      como los facets de producto + param en /sales, /sales/kpis, export;
      FE chips "TIENDA:" con conteos en la tarjeta de filtros).
      Commits: `1e03e78b` (BE + migración índice `mlp_publicationid`,
      IF NOT EXISTS, CONCURRENTLY), `7c3765df` (FE).
      RED visto: 13/14 tests de router fallando (listado sin filtrar, 200 en
      vez de 422, `KeyError: 'stores'`); FE 4 fallando (sin grupo "Filtrar por
      tienda oficial", `stores` undefined).
      Checks: ruff format/check OK; pytest store_filter + sales/export/kpis
      routers + services/ml_sales_query → 283 passed; Postgres
      (`test_filters_stores_postgres.py`, ids de 16 dígitos + EXPLAIN con
      seqscan off usa el índice de `mlp_publicationid`) 5 passed; vitest
      144→145 archivos, 1919→1923 tests; test:visual 9 files OK; eslint 0
      errores (8 warnings previos); lint:css OK; build OK.
- [ ] T2 — Tabla resumen diaria + migración + actualización desde el worker
      de métricas + script de backfill (con remaining/NOT DONE como los otros).
- [ ] T3 — Endpoint del tablero: por producto y por publicación, ventanas,
      markup actual/anterior/mín/máx, series 90d para sparklines, última venta,
      ageing, KPIs con delta vs período anterior, filtros (tienda, fechas,
      marca/subcat/PM, búsqueda, estado/tipo de publicación, alertas),
      paginación y orden. Permiso para ver ganancia.
- [ ] T4 — Pantalla según el diseño + suite visual (capturas 1920/1366,
      claro/oscuro) comparada contra `tablero.png`.

## Entrega

Una PR por tarea (T1 sola es útil ya; T2→T3→T4 en orden).

## Checks

- Backend: `ruff format app/ tests/ && ruff check app/ tests/`, pytest
  focalizado + suite completa SOLA antes de cada PR.
- Frontend: vitest (contar archivos/tests antes y después), `test:visual`,
  `eslint src` 0 errores, `lint:css`, `build`.

## Estado

Creado 2026-10-01. T1 hecho; sigue T2.
