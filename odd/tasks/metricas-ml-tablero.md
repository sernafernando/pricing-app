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
- **REEMPLAZADA 2026-10-02 (decisión del usuario, ver "Sin tabla
  resumen"): ya no existe; el tablero lee las órdenes.**
  Tabla resumen diaria (producto × MLA × día de acreditación; ~~× tienda~~ —
  **reemplazado por la decisión T2 de abajo: la tienda NO va en la clave, se
  resuelve al leer**) con
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
- (T6, writer) `refresh_rollup` toma `pg_advisory_xact_lock(ns,
  hashtext(mla|día))` por bucket, ordenados, ANTES de leer la fuente (mismo
  patrón que `ml_group_metrics/compute.py::_lock_group`). El tablero acepta
  como máximo 366 días, entre 2001-01-01 y 2100-12-31. El CSV se arma por
  páginas de 500 filas sin series. KPI: `rows_with_sales` (productos o
  publicaciones según la agrupación).
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
  calcularlo una vez y no once (una por sentencia). Producción pasa por
  PgBouncer en modo TRANSACCIÓN, así que la tabla vive y muere DENTRO de una
  transacción: `CREATE TEMPORARY TABLE ... ON COMMIT DROP`, dentro de un
  SAVEPOINT de la transacción del request que `Board.__exit__` siempre
  revierte (pase lo que pase, el CREATE se deshace y no queda nada en la
  conexión del servidor para el próximo cliente); el ANALYZE y todas las
  lecturas van adentro. Si algo hace commit/rollback en el medio, el tablero
  falla fuerte (RuntimeError) y la tabla igual ya no existe (ON COMMIT DROP).
  Un error de base a mitad de camino sale como el error original, no como
  "transaction aborted" de la limpieza. Fila de una
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
      Ajuste PgBouncer (pedido del coordinador): RED visto — tras un error de
      base a mitad de camino la limpieza tapaba el error real con
      `InFailedSqlTransaction`, y tras un commit en el medio la tabla seguía
      existiendo en la sesión. GREEN: tests de ciclo de vida en Postgres con
      conexión sin transacción externa (`to_regclass('pg_temp.board_pair_agg')
      IS NULL` tras request OK, tras falla a mitad y tras commit en el medio;
      dos cálculos seguidos en la misma conexión). Sigue en 16 sentencias
      (salen los dos DROP, entran SAVEPOINT y ROLLBACK TO SAVEPOINT); mismos
      tiempos. pytest focalizado 200 passed; no se tocó código compartido.

- [x] T6 (revisión de cuatro lentes, sobre `metricas-ml-tablero-pr`).
      Commits: `12acfcf9` (parsers CSV compartidos en
      `services/ml_sales_query/params.py`), `68c6e5bb` (período ≤ 366 días
      entre 2001-01-01 y 2100-12-31, si no 422), `32e3fda3` (export sin
      series y por páginas de 500), `3b6b4f3a` (`rows_with_sales`; tramos de
      ageing `up_to_30`/`from_31_to_60`/`over_60` obligatorios), `5f402d8e`
      (sub-filas de publicaciones: respuesta vieja descartada por generación,
      error no cacheado), `bc1380f9` (docstring del tablero y doc),
      `3f5b461a` (lock asesor por bucket en `refresh_rollup`).
      RED visto: carrera con dos conexiones reales → el bucket quedó en
      (3 u, 1 orden, $30) en vez de (5, 2, $50); rango 0001..9999 → 500 y
      rangos largos → 200; export → corría la consulta de series; KPI →
      `KeyError: 'rows_with_sales'` y buckets de ageing con default; front →
      la sub-fila vieja no se descartaba y el error quedaba cacheado.
      Checks: ruff OK; pytest focalizado 543 passed; concurrencia 3/3 OK;
      vitest 152 archivos / 1959 tests; test:visual 10 / 72; eslint 0
      errores; lint:css OK; build OK. Suite backend completa, sola: 7712
      passed, 16 skipped.

## Entrega

Una PR por tarea (T1 sola es útil ya; T2→T3→T4 en orden).

## Checks

- Backend: `ruff format app/ tests/ && ruff check app/ tests/`, pytest
  focalizado + suite completa SOLA antes de cada PR.
- Frontend: vitest (contar archivos/tests antes y después), `test:visual`,
  `eslint src` 0 errores, `lint:css`, `build`.

## Estado

Creado 2026-10-01. T1–T4 hechos. 2026-10-02: "Sin tabla resumen" (abajo) reemplaza el
resumen diario: ya NO hay backfill que correr. Falta: medir el tiempo de respuesta
del tablero con datos reales de producción.

## Sin tabla resumen (2026-10-02)

Decisión del usuario (final): el tablero sale de las tablas que YA tenemos,
no de `ml_product_daily_metrics`. "Tenemos todas las operaciones, TODAS! no
entiendo porque tengo que andar backfilleando, porque todo lleva una tabla
nueva, porque nada sale de lo que ya tenemos."

Síntomas que causaba el resumen en producción: 24h=68 > 3d=7d=15d=53 < 30d=99
para un producto (24h salía vivo de las órdenes; el resto de un resumen
incompleto), y abrir las publicaciones de un producto tardaba segundos porque
la sub-fila reconstruía el agregado del tablero ENTERO.

Fuentes (mismas reglas que Ventas ML, para que los números coincidan):
día = `ml_group_metrics.group_date` (acreditación) en hora de Buenos Aires;
plata = `ml_order_metrics`; unidades y MLA = `ml_order_items_ops`; producto =
costo congelado (`frozen_cost_of_item()`); reparto de una orden con varios
ítems por costo congelado; cancelada sin cobertura de ML no suma;
publicación/tienda = `tb_mercadolibre_items_publicados`. TODAS las ventanas,
markups, series, última venta y ageing salen de UNA base por orden, así que
24h ⊆ 3d ⊆ 7d ⊆ 15d ⊆ 30d por construcción.

Rama: `refactor/metricas-ml-sin-rollup` (sobre `feat/metricas-ml-excluir`,
PR #1379). Ruta: delegated direct (writer único). TDD estricto.

- [x] ST1 — Tablero desde las tablas existentes (mismo contrato de API,
      filtros, orden, paginado, export). Tests: ventanas monótonas contra un
      conteo a fuerza bruta en Python; paridad con los KPI de Ventas ML.
      Base única: `services/ml_daily_metrics/sales.py::sale_lines` (una fila
      por ítem vendido) + `last_sales` (última venta de cada par en TODA la
      historia, para ageing). Por request, dentro del SAVEPOINT: tabla
      temporal `board_lines` (producto × MLA × día BA, sólo los días que se
      leen + 24h) y `board_pair_agg` (ventanas, período, comparación, 24h,
      última venta, datos de publicación/producto). Contrato de la API sin
      cambios; el frontend no se toca.
      Reglas (decisiones, mismas que Ventas ML `aggregate.py`):
      plata sólo de órdenes con métricas asentadas (una orden recalculándose,
      fallida o sin calcular suma unidades pero ni bruto ni Total Gauss ni
      costo — el resumen no lo hacía); markup todo-o-nada POR GRUPO (pack):
      si un miembro no tiene Total Gauss y costo, el pack entero queda fuera
      del ratio (`mtg`/`costo`), pero su Total Gauss conocido sigue sumando
      en "Total Gauss"; estado NULL no es cancelada.
      Diferencia aceptada con Ventas ML: en un pack MIXTO (un miembro
      cancelado sin cobertura y otro no) Ventas ML suma el importe del
      cancelado; el tablero no (regla de la venta cancelada).
      RED visto: 30 fallando (el tablero leía el resumen vacío: filas sin
      ventas, `KeyError` de productos vendidos, 24h ≠ ventanas).
      Checks: pytest SQLite (router 46, paridad 1, reglas + propiedad 13) y
      Postgres (`test_board_postgres.py`, ids de 16 dígitos, día BA en SQL,
      reparto NUMERIC; volumen) → 131 passed. El test de 24h del router pasó
      de 4 a 6: la venta de hoy de `board_data` ahora cae también en 24h
      (antes 24h no veía las ventas del resumen).
- [x] ST2 — Sub-filas de publicaciones: sólo los MLAs del producto pedido.
      Test: costo (sentencias y filas) independiente de cuántos otros
      productos hay.
      Con `product_item_id`: los grupos se alcanzan por el índice de
      `ml_order_item_costos.producto_item_id` (y de ahí las órdenes por
      `pack_id`/`order_id`, no por hash de todas), y el espejo de
      publicaciones se lee sólo para los MLAs del producto (antes el
      "último `mlp_id` por MLA" recorría todas las publicaciones).
      Test `test_board_subrows_postgres.py`: el mismo producto solo y entre
      300 productos más (900 publicaciones, 10.800 órdenes): mismas 8
      sentencias, mismas filas en las tablas temporales (12 líneas, 3
      pares), y EXPLAIN ANALYZE (seq scans apagados) con ≤ 48 filas leídas
      por tabla fuente.
      RED visto: sin la restricción de publicaciones, 1.809 filas leídas
      del espejo; sin la del producto, ~21.600 de grupos/ítems/costos y
      10.824 de órdenes.
      Medido en volumen (ST3): sub-filas de un producto entre 2.000 →
      9 sentencias, ~37 ms (antes reconstruía el tablero entero).
- [x] ST3 — Rendimiento en Postgres con volumen real (≈80k grupos en 18
      meses, 90 días densos, ~2k productos, ~6k MLAs): tiempos, sentencias,
      EXPLAIN con índices. Si algo es lento: índices sobre tablas EXISTENTES
      o forma de la consulta, nunca una tabla derivada.
      `test_board_volume_postgres.py` (local, Postgres 18, `-s`): 81.000
      grupos en 18 meses (20.000 en los últimos 90 días, todos los días con
      ventas; packs, multi-ítem, canceladas, sin resolver, recalculándose),
      89.100 órdenes, 101.828 ítems, 2.000 productos, 6.000 MLAs.
      - Tablero (página + KPIs + chips + detalle + series): **17
        sentencias** con página de 10, 50 o 200, por producto o por
        publicación, con filtros o exclusiones (15 si la página sale vacía);
        **~600–690 ms** en caliente (~1,4 s la primera, que compila).
        Grueso: `board_lines` ~190 ms, `board_pair_agg` ~185 ms (de los
        cuales ~165 ms es la última venta de cada par sobre TODA la
        historia, para el ageing), ANALYZE ~50 + ~57 ms; KPIs ~9 ms + serie
        ~14 ms, cada chip 2–13 ms, página ~17 ms, detalle ~1 ms, series de
        la página ~4 ms. 241 filas devueltas para una página de 10.
      - Sub-filas de un producto: **9 sentencias, ~37 ms**.
      - Export, primera transacción (claves ordenadas + página de 500, sin
        series): **9 sentencias, ~536 ms**; cada página siguiente igual.
      - EXPLAIN: las líneas del request llegan a `ml_group_metrics` por
        `ix_ml_group_metrics_group_date` (BitmapOr de los tres rangos:
        período+90 días, comparación, 24h); grupo→órdenes por hash sobre la
        clave del grupo; sub-filas por `ix_ml_order_item_costos_producto_
        item_id` y `pack_id`/PK de órdenes (ST2).
      Forma de consulta corregida en el camino (medido): unir grupo→órdenes
      con el OR de índices para TODO el tablero anidaba 54k lazos (~120 ms
      más) y dos ventanas con particiones distintas ordenaban dos veces:
      el tablero entero usa igualdad de clave (hash) y una sola partición
      (grupo, orden); el OR por índice queda sólo para un producto. Con eso
      el CREATE de líneas bajó de ~500 a ~190 ms. JIT apagado no cambiaba
      nada (medido) y analizar o no `board_lines` daba lo mismo (se deja).
      Sin índices nuevos: no hubo un índice sobre tablas existentes que
      sirviera; lo que queda es volumen leído por hash (la historia completa
      para el ageing). Antes (con resumen): ~370 ms el tablero, pero con
      números incompletos y segundos para abrir las sub-filas.
- [x] ST4 — Sacar el resumen: hook del worker, lock asesor, backfill y sus
      tests, modelo, migración que borra la tabla. "Actualizado hace X" desde
      datos existentes.
      Borrado: `services/ml_daily_metrics/rollup.py` (escritor, lock asesor
      por bucket, `stale_buckets`), el hook en
      `order_metrics/store.py::store_order_metrics` (vuelve a sólo
      recalcular y guardar el grupo), `models/ml_daily_metrics.py`,
      `scripts/backfill_ml_daily_metrics.py` y los tests del resumen,
      del backfill y de la concurrencia del resumen; la tabla de las
      fixtures Postgres de `tests/conftest.py`. Lo que se seguía usando
      (`frozen_cost_of_item`, `business_day`, `BUSINESS_TZ`, `NO_PRODUCT`)
      vive en `services/ml_daily_metrics/sales.py` (desde ST1).
      ~~Migración `20261002_drop_ml_product_daily_metrics`~~ — **sacada en
      ST7 (revisión): el DROP va en una PR posterior, ver ST7.**
      `ix_ml_group_metrics_group_date` (de
      `20261001_ix_board_reads`) se queda: lo usa el tablero.
      "Actualizado hace X": `MAX(ml_ops_sync_cursor.last_success_at)` de
      `sweep`/`ml_activity`, lo mismo que el sync-status de Ventas ML
      (desde ST1); el frontend no cambia.
      Rama rebasada sobre `origin/main` (que ya incluye #1379 y la
      migración de autovacuum) para que la migración nueva no bifurque.
      RED visto: 7 fallando (head, módulos presentes, tabla en la
      metadata, `store.py` mencionaba el resumen, revisión inexistente).
      Checks: ruff OK; pytest migraciones + ml_daily_metrics +
      order_metrics + ml_group_metrics + router + paridad + export Ventas
      ML + scripts → 399 passed; round trip de la migración en Postgres
      OK.
- [x] ST5 — Checks completos (ruff, suite backend sola, vitest, test:visual,
      eslint, lint:css, build).
      `ruff format app/ tests/` + `ruff check app/ tests/` OK. Suite backend
      completa, sola (`-p no:randomly`, `ENVIRONMENT=development`): **7755
      passed, 16 skipped**. (Una corrida previa sin `ENVIRONMENT` daba 404
      en `test_openapi_schema_loads`: el entorno por defecto es producción y
      apaga /docs; no es del cambio.) Frontend sin cambios en esta rama:
      vitest 143 archivos / 1896 tests antes y después; test:visual 10
      archivos, 76 passed + 2 expected fail; eslint 0 errores (8 warnings
      previos); lint:css OK; build OK.
      Commits: `5e1d54fb` (ST1), `6d67f34e` (ST2), `4e8e01f8` (ST3),
      `8e7553a1` (ST4). Sin push.
- [x] ST6 (revisión, hallazgos 1 y 3) — Plata exacta al centavo y Total
      Gauss sólo de órdenes `ok`/`provisional`.
      Hallazgo 1, decidido por Ventas ML: su lector (`OrderMetrics`) exige
      "unresolved ⇒ total_gauss NULL" y RECHAZA una fila que lo rompa
      (ValueError; el KPI daría 500). Para Ventas ML una orden `unresolved`
      suma bruto pero nunca Total Gauss ni markup. El tablero decide por el
      estado (como el resumen viejo): una fila `unresolved` con Total Gauss
      cuenta unidades y bruto, nunca Total Gauss ni markup.
      Hallazgo 3: todas las ramas del reparto por ítem son NUMERIC
      explícitas (`CAST(... AS NUMERIC)`, `Decimal` literal); los totales
      se redondean al centavo UNA vez al final (ROUND_HALF_UP), como las
      sumas de valores de 2 decimales de Ventas ML.
      Test `test_board_money_postgres.py` (Postgres, contra
      `aggregate_order_metrics` real): 3 ítems de igual peso sobre 100,00,
      pack con pesos 1 y 2 sobre 10,01, reparto 1/3–2/3 por cantidad,
      `unresolved` con costo: bruto, Total Gauss (111,06) y markup iguales
      como `Decimal` exacto; `pg_typeof` de las líneas = numeric. Paridad
      SQLite con una orden `unresolved` con costo.
      RED visto: Total Gauss `111.0599999999999999990000` ≠ `111.06`; la
      fila `unresolved` con Total Gauss sumaba 12,340. (El tipo ya salía
      NUMERIC en Postgres porque psycopg2 manda `1.0` como literal numérico;
      ahora es explícito y no depende del driver.)
- [x] ST7 (revisión, hallazgo 2) — Borrado en dos fases.
      El DROP de la migración corre en el deploy ANTES de que reinicien los
      workers: los workers viejos todavía llaman a `refresh_rollup` dentro
      de `store_order_metrics`, así que cada guardado de métricas fallaría
      (`UndefinedTable`) y se revertiría hasta el reinicio. Esta rama saca
      el CÓDIGO (modelo, escritor, hook, backfill) y deja la tabla en la
      base, sin uso; la migración que la borra
      (`DROP TABLE IF EXISTS ml_product_daily_metrics`, con `lock_timeout`,
      sus índices `_day`, `_mla_day`, `_updated_at` se van con ella) va en
      una PR POSTERIOR, después de desplegar esta. Head único de vuelta en
      el de main (`20261002_autovacuum_tablas_calientes`).
      Test `tests/unit/test_rollup_removed.py` (antes
      `test_migration_drop_ml_product_daily_metrics.py`): módulos del
      resumen inexistentes, ningún modelo mapea la tabla, `store.py` no lo
      menciona, y NINGUNA migración de esta línea la borra.
      RED visto: `20261002_drop_ml_product_daily_metrics drops
      ml_product_daily_metrics`.
      **Para el cuerpo de la PR:** "La tabla `ml_product_daily_metrics`
      queda en la base, sin uso. Se borra en una PR siguiente, después de
      desplegar esta: si la migración la borrara en este deploy, los
      workers viejos (que todavía la refrescan al guardar métricas)
      fallarían hasta reiniciarse."
      Pendiente (PR siguiente): migración de DROP de la tabla.
      Checks ST6+ST7: ruff OK; pytest focalizado (ml_daily_metrics, router,
      paridad, migraciones) 92 + 16 passed; suite backend completa, sola
      (`ENVIRONMENT=development`): 7756 passed, 16 skipped.
- [x] ST8 (revisión final) — Series en centavos y matcher de DROP.
      Cada punto de dinero de las series diarias de KPIs pasa por `cents()`
      (half-up, igual que las filas) y viaja como `Decimal`; el markup de
      cada día de la serie de 90 días sale de las sumas del día ya
      redondeadas, como el de la fila. RED visto: punto de Total Gauss
      `111.06` float ≠ `Decimal('111.06')`; en la API un producto de 1/3
      mandaba `33.33333333333333` en la serie.
      `test_no_migration_of_this_release_drops_the_table` usa un matcher
      (`DROP TABLE ... ml_product_daily_metrics` dentro de una sentencia, u
      `op.drop_table(<la tabla o su constante>)`) con tests propios: atrapa
      la migración vieja de drop y no da falso positivo con `DROP INDEX` ni
      con otro `DROP TABLE` en un archivo que sólo nombra la tabla. RED:
      `NameError` (el matcher no existía).
      Checks: ruff OK; pytest focalizado 112 passed.
- [x] ST9 (notas del pre-push) — Sub-filas de "sin producto" acotadas,
      guarda no vacía del export y docstrings partidos.
      Producto 0 (ítems sin costo congelado) no tiene índice de producto:
      sus sub-filas ahora van por la unión estrecha grupo→órdenes y su
      última venta sólo mira la ventana del request (período, comparación,
      serie de 90 días, 24h), nunca toda la historia. Test en
      `test_board_subrows_postgres.py`: con 300 productos más (10.800
      órdenes viejas), mismas 8 sentencias, mismas filas temporales y ≤ 12
      filas leídas por tabla fuente. RED visto: 10.812 órdenes/ítems,
      10.800 costos y 900 publicaciones leídas.
      El chequeo "el export no arma series" primero prueba que el marcador
      SÍ aparece en una página del tablero (pasó de una: el chequeo no era
      vacío, ahora no puede serlo).
      Checks: ruff OK; pytest focalizado 109 passed.

## Período y stock (2026-10-05)

Pedido del usuario: "el filtro de fecha de las métricas no está siendo muy
útil, quizás deberíamos hacer un toggle que muestre solo los productos dentro
de ese rango de fechas, no que no muestre cuanto se vendió hace 30d, pero que
los productos que se vean por ejemplo sean solo los de hoy y no los 3000,
también un filtro de productos sin stock para elegir verlos o no verlos, ver
las métricas de solo sin stock también, para ver si hay que recomprar algo".
Después: "faltaría también uno para ver los de ageing, y poder ordenar por
diferentes columnas".

Rama: `feat/metricas-ml-periodo-y-stock` desde `origin/main`, PR contra main.
Ruta: delegated direct (writer único). TDD estricto (RED visto antes de cada
arreglo). Runner: backend `pytest` (venv de pricing-app-5), frontend `vitest`
(`pnpm test`, `pnpm test:visual`).

### Exploración: de dónde sale el stock

- `productos_erp.stock` (`backend/app/models/producto.py:28`): el stock del
  depósito 1 que trae `erp_sync.sincronizar_erp` en vivo del ERP
  (`fetch_stock_erp`, `ItemStorage_funGetXMLData` con `intStor_id=1`,
  `backend/app/services/erp_sync.py:159-177`, guardado en
  `erp_sync.py:349-401`). Es el "Stock" que ya usa el resto de la app para un
  producto ERP: columna Stock y filtros "Con stock"/"Sin stock" de Productos
  (`api/endpoints/productos_stats.py:82-86`, `productos_pricing.py:298-299`,
  `:904-908`), pestaña Stock del dashboard TP-Link
  (`api/endpoints/dashboard_tplink.py:689`).
  Frescura: se reescribe cada vez que corre `sincronizar_erp` — el cron de
  `scripts/sync_completo.py` (cada 10 min de 6 a 21 h según su docstring y
  `crontab_fixed.txt`; `backend/CRON_COMPLETO_OPTIMIZADO.md` de 2026-01
  propuso sacarlo, el cron real de producción no se puede ver desde el repo)
  y el botón de sync manual (`api/endpoints/sync.py`).
- `stock_por_deposito` (`models/stock_por_deposito.py`,
  `scripts/sync_stock_por_deposito.py`): mismo origen del ERP pero por
  depósito, cron diario sugerido (03:00); sólo lo usa Consultas
  (`routers/consultas.py`) con depósitos elegidos por el usuario. Más viejo
  (diario) y sin un "depósito vendible" definido para un producto: no.
- GBP reporte 78 `Stock_Disponible`: lo lee la conciliación de Tienda Nube
  por HTTP en el momento; no está guardado por producto: no.
- `tb_item_storage.itst_cant` (espejo): el propio `erp_sync` documenta que
  NO es real-time (`erp_sync.py:252-256`): no.

**Elegido: `productos_erp.stock`**, unido por `item_id` al producto de la
fila (un LEFT JOIN por PK dentro de la consulta de filas del tablero, nunca
una consulta por fila).

### Decisiones

- (PS1) "Solo con ventas en el período" = la FILA (producto, o publicación
  agrupando por publicación) tiene ≥ 1 unidad vendida en el período elegido
  (`units > 0`, la misma definición que el KPI "con ventas"). Filtra QUÉ
  filas, no los números: se aplica sobre la fila ya agregada, así que las
  ventanas 24h…30d, markups, series y ageing de una fila que pasa incluyen
  TODAS sus ventas (también las de otras publicaciones o días fuera del
  período). KPIs, conteos de chips, paginado y CSV usan el mismo conjunto de
  filas; con el toggle prendido "con ventas X de Y" da X = Y. Parámetro
  `solo_con_ventas` (bool): por defecto `true` en la API (lo pidió el
  usuario); `BoardFilter.solo_con_ventas` por defecto `False` (un filtro
  vacío no filtra, como los demás). El frontend lo manda siempre explícito.
- (PS1/PS2/PS3) Sub-filas de publicaciones de un producto: los filtros de
  FILA (solo con ventas, stock, ageing, alertas) ya decidieron que el
  producto se ve; sus sub-filas muestran todas sus publicaciones que pasan
  los filtros de PAR (tienda, estado, tipo, marca, búsqueda), para que sumen
  lo mismo que la fila del producto (igual que hoy con las alertas).
- (PS2) Stock de la fila: producto → `productos_erp.stock` de ese producto;
  publicación → el del producto ACTUAL de la publicación (el mismo producto
  que ya muestra la fila). Chips (tri-estado, como Publicación/Tipo):
  "Con stock" (> 0), "Sin stock" (<= 0) y "Sin dato" (el producto no está en
  `productos_erp` o su stock es NULL — por ejemplo "Sin producto", ítems sin
  costo congelado). "Sin dato" va aparte y no dentro de "Sin stock": el
  pedido es ver qué recomprar, y meter ahí filas que no sabemos qué son
  ensuciaría esa lista. La columna muestra "—" en "Sin dato".
  Columna Stock: sale del grupo "Sell-in / Sell-out (Próximamente)" y pasa a
  "Rotación", porque ya es real.
- (PS3) Ageing: chips tri-estado con los MISMOS tramos que el KPI (≤ 30,
  31–60, > 60 días desde la última venta, o desde el inicio de la
  publicación si nunca vendió) y los mismos colores que la columna. La
  alerta "Ageing > 60d" es exactamente el tramo "> 60 d" (misma expresión en
  SQL), así que sus conteos coinciden; las dos quedan. Con un chip de ageing
  activo y "Solo con ventas" prendido, aparece un aviso junto al toggle
  ("Ocultando productos sin ventas en el período"): el toggle no se cambia
  solo.
- (PS4) Orden: cualquier encabezado numérico (24h…30D, Markup act., vs
  anterior, Facturado, Total Gauss, Última venta, Ageing, Stock) ordena en
  SQL sobre todo el conjunto filtrado y después pagina, siempre cerrando con
  la clave única de la fila. Primer clic desc (asc para Producto), segundo
  invierte. Ordenar por margen sigue pidiendo `ver_ganancia` (403); sin el
  permiso esas columnas no existen en la UI. "Limpiar filtros" no toca el
  orden (no es un filtro).

### Tareas

- [x] PS1 — Toggle "Solo con ventas en el período" (BE param + FE switch +
      params + reset). Tests: con "Hoy" sólo lo vendido hoy, con su 30d
      incluyendo ventas viejas; OFF = catálogo entero.
      Ruta: inline (writer único). RED visto: backend 5/7 fallando (con "Hoy"
      volvían los 4 productos, el CSV traía 4 filas, `quizas` daba 200);
      frontend 5 fallando (sin `solo_con_ventas` en los params, sin switch).
      Los tests viejos del router que hablan del catálogo entero piden
      `solo_con_ventas=false` explícito (`CATALOG`): el cambio del default
      es el contrato nuevo, no una regresión.
      Checks: router + paridad + servicios del tablero 102 passed; vitest de
      la página y params 23 passed; ruff OK.
- [x] PS2 — Stock: columna, chips Con/Sin stock/Sin dato con conteos, en
      SQL (filas, KPIs, chips, CSV), CSV con columna Stock. Conteo de
      sentencias ajustado con justificación; volumen sigue pasando.
      PS1 commit: `3c3da1b4`. Ruta: inline (writer único).
      SQL: el stock es un LEFT JOIN por PK de `productos_erp` sobre el
      producto de la fila DENTRO de la subconsulta de filas (`Board.rows`),
      con su tramo (`stock_bucket`); el filtro va sobre la fila agregada, así
      que página, KPIs, chips y CSV ven las mismas filas. Conteos de los
      chips de stock: UNA sentencia más (sumas condicionales con su eje
      apagado). Tablero en volumen: **18 sentencias** (antes 17; la nueva es
      la de los chips de stock, ~3 ms), igual con página 10/50/200, por
      producto o publicación, con exclusiones y con stock + solo con ventas;
      ~660–750 ms en caliente (antes ~600–690). CSV: columna "Stock" al
      final. Fixture Postgres del tablero: `productos_erp` mínima con
      `stock` (en CI la crea el fixture; sin la columna el join fallaría).
      RED visto: router 14/14 fallando (`KeyError: 'stock'`, filtros
      ignorados, 200 en vez de 422); frontend 4 fallando (sin grupo "Filtrar
      por stock", sin params, celda "—" de próximamente).
      Checks: router + paridad + servicios del tablero (Postgres incluido,
      volumen) 117 passed; vitest página + params 27 passed; ruff OK.
- [ ] PS3 — Chips de Ageing + aviso con "Solo con ventas".
- [ ] PS4 — Orden por columnas (stock incluido, flecha lucide, aria-sort).
- [ ] PS5 — Checks: ruff, pytest focalizado, vitest (antes 143 archivos /
      1899 tests), test:visual, eslint, lint:css, build, suite backend
      completa sola.
