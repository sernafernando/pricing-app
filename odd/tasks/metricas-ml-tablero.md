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
- (T2, writer) La tabla resumen (`ml_product_daily_metrics`) NO guarda la
  tienda: la clave es producto × MLA × día y la tienda se resuelve al leer
  desde el `mlp_official_store_id` ACTUAL de la publicación. Es la única
  forma de cumplir "si una publicación cambió de tienda, su historial se
  mueve con ella" sin cron (una tienda congelada en la fila quedaría vieja).
- (T2, writer) Ítem sin costo congelado → producto `0` ("sin producto").
  Venta cancelada sin cobertura de ML no suma; "Cubierta por ML" sí (la
  plata llegó). Total Gauss/costo sólo de órdenes `ok`/`provisional` con
  ambos valores; el resto suma unidades y cuenta en `unresolved_orders`.
  Bruto sólo de órdenes en ARS. Día = `ml_group_metrics.group_date` en hora
  de Buenos Aires.
- (T3, writer) Ventanas 3d/7d/15d/30d y la serie de 90 días terminan en
  `date_to` (hoy por defecto); 24h es móvil desde ahora, leído de las
  órdenes. "Margen Act." y Facturado/Total Gauss son del período elegido.
  Ageing = días desde la última venta; si nunca vendió, desde el inicio de
  la publicación más vieja. Alertas: "Sin ventas 30d" = 0 unidades en 30d;
  "Ageing > 60d"; "Margen cayendo" = markup del período ≥ 1 pp por debajo
  del de comparación. "Mejor" publicación = la que más Total Gauss dejó en
  el período (facturado si no ve ganancia). Orden por defecto: facturado
  desc. Universo = publicaciones del espejo ERP + pares (producto, MLA)
  vendidos sin fila de publicación. Permisos nuevos `ml_metricas.ver` y
  `ml_metricas.ver_ganancia` (ADMIN y GERENTE); sin el segundo, Total
  Gauss/markup vuelven `null` y ordenar/filtrar por margen es 403. Se agregó
  export CSV (el diseño tiene el botón).
- (T4, writer) Rótulos "Markup" donde el diseño de Stitch dice "Margen"
  (Markup act., Markup promedio, "Markup cayendo"): el número ES markup
  (Total Gauss / costo) y llamarlo margen sería mentir; el parámetro de la
  alerta sigue siendo `margen_cayendo`. "Comparar con: Mismo período año
  pasado" (mismas fechas un año atrás), no "mismo mes".
- (T4, writer) Se agregó una columna "Tendencia" de unidades (semanas de
  los últimos 90 días) en el grupo Ventas: el pedido incluye "tendencia de
  ventas con mini gráfico" y el diseño sólo la tenía en las tarjetas. Se
  puede ocultar desde Columnas.
- (T4, writer) Sparklines en SVG inline propio (recharts está en el
  proyecto pero 50 filas × 2 gráficos no lo justifican). El encabezado de la
  tabla NO es sticky vertical: la tarjeta es el contenedor del scroll
  horizontal y un `th` sticky se pega a ella, no a la página.
- (T5, writer) Tabla TEMPORARY por request para el agregado por par:
  calcularlo una vez y no once (una por sentencia). Es privada de la
  conexión, se borra al final (y `DROP IF EXISTS` al empezar por si una
  request anterior en la misma conexión murió a mitad). Fila de una
  publicación: su producto es el `item_id` actual de la publicación (antes,
  el que más vendió en el período). Orden por "última venta" usa el DÍA de
  la última venta.
- (T4, writer) Tienda va en su propia franja, la primera de chips (debajo de
  fechas/búsqueda); Producto + Publicación/Tipo en la siguiente; Alertas al
  final. Sin el permiso de ganancia no se muestran las columnas de markup/
  Total Gauss ni la alerta "Markup cayendo".

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
- [x] T2 — Tabla resumen diaria + migración + actualización desde el worker
      de métricas + script de backfill (con remaining/NOT DONE como los otros).
      Commits: `9beb3c9b` (+ `76345136`: el test de la migración
      `ml_ops.resincronizar` fijaba el head por nombre y se rompía con
      cualquier migración nueva).
      Hook: `store_order_metrics` → tras guardar el grupo, `refresh_rollup`
      de los buckets (MLA, día) de los MLAs del grupo, en el día nuevo y en
      el anterior. Backfill: `python -m app.scripts.backfill_ml_daily_metrics
      --dry-run` y luego sin flag (correr en prod después del deploy).
      RED visto: 10/13 fallando (filas faltantes, KeyError) con el stub; el
      backfill por ImportError del módulo.
      Checks: ruff OK; pytest order_metrics + ml_group_metrics + workers +
      scripts + ml_daily_metrics + routers ventas_ops + unit → 3704 passed
      (1 fallo encontrado y arreglado en `76345136`); Postgres: rollup con
      ids de 16 dígitos + upsert real + borrado de bucket vacío, y round
      trip de la migración, OK.
- [x] T3 — Endpoint del tablero: por producto y por publicación, ventanas,
      markup actual/anterior/mín/máx, series 90d para sparklines, última venta,
      ageing, KPIs con delta vs período anterior, filtros (tienda, fechas,
      marca/subcat/PM, búsqueda, estado/tipo de publicación, alertas),
      paginación y orden. Permiso para ver ganancia.
      Commit: `623f8b2c`. `GET /api/ml-metricas/board`,
      `/board/products/{id}/publications`, `/board/export`.
      RED visto: 24/24 fallando (404, el router no existía).
      Checks: ruff OK; router 24 passed; Postgres (24h por
      `member_order_ids` ARRAY con ids de 16 dígitos) OK; migración de
      permisos OK. Pendiente de verificar con datos de producción: tiempo de
      respuesta (carga el espejo de publicaciones entero y agrega en Python).
- [x] T4 — Pantalla según el diseño + suite visual (capturas 1920/1366,
      claro/oscuro) comparada contra `tablero.png`.
      Commits: `27613a0a` (BE: miniatura por fila y tramos del ageing),
      `ed492aff` (FE). Ruta `/metricas-ml`; menú "Métricas ML" + badge
      "Nuevo"; el viejo pasa a "Métricas ML (anterior)" (misma URL).
      RED visto: tests de utils/Sparkline/página fallando por módulo
      inexistente; nav y título viejo 3 fallando; Pagination `summary` 1
      fallando; backend miniatura/ageing 3 fallando (KeyError).
      Checks: vitest 145→151 archivos, 1923→1953 tests (todo verde);
      test:visual 9→10 archivos, 72 passed; eslint 0 errores (8 warnings
      previos); lint:css OK; build OK. Suite visual: sin overflow de celdas,
      sin scroll horizontal de página, la tabla scrollea dentro de la
      tarjeta, Producto queda fijo al scrollear, plata/chip/mín-máx en una
      línea y enteros. Capturas (no commiteadas): `VITE_METRICAS_SHOTS_DIR`.
- Suite backend completa (sola, `-p no:randomly`): 7669 passed, 16 skipped.
  Encontró 2 presupuestos de queries de Ventas ML que contaban
  `ml_order_items_ops` ≤ 1; el facet de Tienda suma una consulta constante
  (no por fila) → presupuesto 2, commit aparte.

- [x] T5 (pedido del coordinador antes de la PR) — Rendimiento del tablero.
      Commit: `03bb71ef`. Ruta: delegated direct (mismo writer).
      Antes: el tablero cargaba el espejo de publicaciones entero y todas las
      filas del período en Python. RED medido en Postgres con volumen
      (2.000 productos, 6.000 MLAs, 90 días ≈ 216k filas de resumen):
      6 sentencias pero **230.001 filas** devueltas por request y ~2,8–3,5 s;
      sin sentencia con LIMIT.
      Ahora: por request se materializa UNA vez el agregado por (producto,
      MLA) en una tabla TEMPORARY privada de la conexión (`board_pair_agg`,
      una sola pasada por el resumen + `ANALYZE`), y todo lo demás la lee:
      página con ORDER BY + LIMIT/OFFSET en SQL, KPIs, conteos de chips
      (CTEs MATERIALIZED, cada uno sin su propio eje), y detalle + series de
      90 días de la página en UNA consulta cada una. El espejo de
      publicaciones nunca se carga en Python.
      Medido (local, Postgres 18, `-s`): **16 sentencias** por request con
      página de 10, 50 o 200 y agrupando por producto o publicación (14 si la
      página sale vacía); **443 filas** devueltas para una página de 10;
      **~370 ms** página de 50, ~430 ms página de 200, ~400 ms con filtros
      (tienda+marca+estado+búsqueda), ~950 ms la primera request en frío. El
      grueso: crear el agregado ~155 ms, `ANALYZE` ~38 ms, serie de KPIs
      ~40 ms; el resto 2–12 ms cada una.
      EXPLAIN: con el planner por defecto, el detalle y la serie de la página
      llegan al resumen por índice (nunca Seq Scan); "actualizado hace" usa
      `ix_ml_product_daily_metrics_updated_at`. Sin los `IN` sobre la clave
      casteada y sin estadísticas de la tabla temporal el planner anidaba
      loops (0,7 s un conteo de chip): por eso el `ANALYZE` y los CTE
      materializados.
      Índices nuevos (migración `20261001_ix_board_reads`, CONCURRENTLY, un
      solo head): `ml_group_metrics.group_date` (ventana 24h) y
      `ml_product_daily_metrics.updated_at`.
      Ventas ML: EXISTS de tienda + marca + subcategoría juntos, EXPLAIN con
      seqscan apagado sin Seq Scan en publicaciones, ítems, costos ni
      productos; y prueba de que se combinan (tienda ∧ marca).
      Checks: ruff OK; pytest focalizado 241 passed; volumen Postgres 4
      passed; router del tablero 25 passed sin cambios de contrato. Suite
      backend completa, sola: 7676 passed, 16 skipped. Frontend sin cambios
      (no se re-corrió).

## Entrega

Una PR por tarea (T1 sola es útil ya; T2→T3→T4 en orden).

## Checks

- Backend: `ruff format app/ tests/ && ruff check app/ tests/`, pytest
  focalizado + suite completa SOLA antes de cada PR.
- Frontend: vitest (contar archivos/tests antes y después), `test:visual`,
  `eslint src` 0 errores, `lint:css`, `build`.

## Estado

Creado 2026-10-01. T1–T4 hechos. Falta: correr el backfill en producción después del deploy y medir el tiempo de respuesta del tablero con datos reales.
