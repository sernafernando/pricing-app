# Métricas ML — vista "Agrupado" (marca, categoría, subcategoría, tienda, PM)

## Objetivo

Tercera vista del tablero Métricas ML junto a Productos y Publicaciones: filas
que agrupan por una dimensión elegida (Marca, Categoría, Subcategoría, Tienda,
PM). Pedido del usuario: "Las métricas tendría que tener vista de agrupación
además de las dos que ya existen (productos y publicaciones) para poder agrupar
por marca, categoría, sub categoría, tienda, pm...".

## Problema

El tablero sólo agrega por producto o por publicación. Para ver cómo rinde una
marca, una tienda o un PM hay que filtrar y leer los KPIs de a uno.

## Decisiones

- Misma base de siempre: `sales.sale_lines` -> tablas TEMPORARY del request
  (`board_lines`, `board_pair_agg`, SAVEPOINT siempre revertido, PgBouncer).
  No se crea ninguna tabla (regla del proyecto: sin tablas derivadas).
- La vista agrupada es `group_by=group` + `dimension=marca|categoria|subcategoria|tienda|pm`.
- Los filtros de FILA (stock, ageing, alertas, "solo con ventas") se deciden por
  PRODUCTO, igual que en la vista Productos, ANTES de agrupar: el grupo suma los
  pares (producto, MLA) de los productos que sobreviven. Los filtros de PAR
  (tienda, estado, tipo, marca, categoría, subcategoría, PM, búsqueda) ya filtran
  los pares. Así los totales de los grupos cierran con los KPIs (mismos filtros).
- Markup del grupo = SUM(total_gauss)/SUM(costo) sobre los pares del grupo (nunca
  promedio de porcentajes); sin costo -> null.
- Ageing / última venta del grupo = la venta MÁS RECIENTE del grupo (ageing = días
  desde ahí; si nunca vendió, desde la publicación más vieja), la misma regla que la
  fila de producto. Stock = suma del stock de los productos DISTINTOS del grupo
  (un producto cuenta una vez por grupo). Alertas por fila: no aplican a un grupo
  (son filtros de producto).
- Tienda: la tienda sale de la publicación; los ids que comparten `clave` en
  `ml_tiendas_oficiales` son UNA fila ("TP-Link" = 2645 + 471846). Un producto que
  vende en dos tiendas aporta a cada una SÓLO lo vendido en sus publicaciones
  (cada venta pertenece a una publicación): los totales cierran. Su stock cuenta
  en cada tienda donde tiene publicaciones.
- PM: por el par marca+categoría (`marcas_pm`, upper()), igual que el filtro PM. Si
  el par tuviera dos filas que sólo difieren en mayúsculas, gana el menor
  `usuario_id` (una fila por par, así un producto nunca cuenta en dos PM).
- "Sin marca / categoría / subcategoría / tienda / PM": una fila propia para los
  nulos/vacíos.
- Subcategoría muestra el nombre (`subcategorias_grupos`), no el id.
- Despliegue de un grupo: sus PRODUCTOS (los mismos que sumó), con las ventas de
  ese grupo (en Tienda: sólo las publicaciones de esa tienda).
- Permisos: igual que el tablero. Sin `ml_metricas.ver_ganancia`, Total Gauss/markup
  vuelven null y ordenar por margen es 403.

## Alcance autorizado

`backend/app/services/ml_daily_metrics/board.py` (+ módulo nuevo de agrupación si
hace falta), `routers/ml_metricas.py`, sus tests (conftest Postgres incluido);
`frontend/src/pages/MetricasML.jsx`, `components/metricasMl/*`,
`utils/metricasMl*`, tests vitest y visual. No se toca Ventas ML ni Productos.

## Modo de pruebas

Strict TDD: habilitado (fuente: instrucciones del proyecto/usuario). Runners:
backend `pytest` (SQLite + `@pytest.mark.postgres` contra `POSTGRES_TEST_URL`),
frontend `pnpm test` (vitest, proyecto unit) y `pnpm test:visual`.

## Ruta por tarea

Todas: delegated direct (un writer). Evidencia del trigger: cada tarea toca 2+
archivos no triviales.

## Tareas

- [x] T1 Servicio: filas agrupadas por dimensión (SQL set-based sobre los pares), 5 dimensiones, "Sin X", clave de tienda, markup como razón de sumas, conciliación con KPIs. Tests Postgres.
- [x] T2 Servicio: despliegue de un grupo a sus productos (scope por grupo) + conteo/KPIs de grupos + techo de sentencias.
- [x] T3 Router: `group_by=group&dimension=`, respuesta, endpoint de productos del grupo, export CSV agrupado, permisos. Tests de router.
- [x] T4 Frontend: params, selector de dimensión, vista Agrupado (tabla, orden, KPIs), vitest.
- [x] T5 Frontend: despliegue a productos, export, estado visual (`test:visual`).
- [x] T6 Medición en el fixture de volumen + verificación completa.

## Criterios de aceptación

1. Las 5 dimensiones agrupan; nulos van a "Sin X"; tienda por clave es UNA fila.
2. Suma de unidades y facturado de los grupos = KPIs sin agrupar (mismos filtros).
3. Markup del grupo = SUM(gauss)/SUM(costo); sin ver_ganancia no hay márgenes.
4. Todos los filtros y facetas siguen funcionando; orden por columnas.
5. Un grupo se despliega a sus productos.
6. CSV agrupado (lista fija de columnas, guarda de fórmulas, tope).
7. Sentencias por request acotadas (techo con test).

## Verificación

pytest (tests tocados + volumen + `pytest tests -q` con ENVIRONMENT=testing),
`ruff format --check app/ tests/`, `ruff check app/`, `pnpm test -- --run`,
`pnpm lint`, `pnpm lint:css`, `pnpm build`, `pnpm test:visual`.

## Progreso / evidencia

- T1 (`d9d732e4`): RED = ImportError (`board.NO_GROUP` inexistente al coleccionar); GREEN = 31 tests `test_board_groups_postgres.py` (5 dimensiones, "Sin X", clave de tienda, markup razón de sumas, conciliación con KPIs, filtros por producto antes de agrupar, stock una vez por producto, orden, paginado). Servicio: `ml_daily_metrics/groups.py` + `Board.group_page/group_rows/group_counts/group_keys/groups_for_keys`.
- T2 (`597286bf`): RED = `TypeError: Board() got an unexpected keyword argument 'group_key'`; GREEN = 41 tests del archivo (suma de productos == fila del grupo en las 5 dimensiones; tienda abre sólo las ventas de esa tienda; filtros de fila deciden por producto entero).
- T3 (`abad3124`, paginado y plan en `aef7745f`): RED = 14 de 20 tests de router (dimension ignorada, 404 en `/board/group-products`, sin `products_count`); GREEN = 22 tests `test_ml_metricas_board_groups_router.py` (agrupado, conciliación con KPIs, permisos, abrir grupo paginado con `total`, CSV agrupado con cabecera fija + guarda de fórmulas + tope + paginado por claves, techo de sentencias).
- Hallazgo de plan (volumen): abrir un grupo con el filtro de pertenencia como `tuple IN (subconsulta)` estimaba 1 fila y anidaba loops (series de página: 3,8 s). Arreglo: la clave y la etiqueta del grupo son COLUMNAS de la tabla de pares (`gkey`/`glabel`, los joins chicos corren una vez al armarla) y abrir un grupo es `gkey = :key` (+ un CTE MATERIALIZED de claves sólo si hay filtros de fila): 565 ms con 100 de 800 productos. El despliegue se pagina (`limit`<=500, default 100) porque una marca puede tener miles de productos.
- Decisiones: ageing/última venta del grupo = su venta más reciente (igual que la fila de producto); stock = suma de los productos distintos (producto sin stock conocido no suma; grupo sin ninguno -> null); alertas no aplican a un grupo. Con "solo con ventas" un grupo sin unidades en el período (p. ej. una tienda donde el producto no vendió) también se oculta. Total Gauss de órdenes con varios ítems se reparte en fracciones de centavo: cada grupo redondea su suma una vez, así que la suma de grupos difiere del KPI en <= 1 centavo por grupo (unidades y facturado cierran exactos).
- T4+T5 (`6965735b`, un solo commit: la vista, el selector y el despliegue comparten página y tabla; `59eda552` visual): RED = 16 tests de `MetricasML.groups.test.jsx` (sin botón "Agrupado", sin `dimension`, sin despliegue) y 2 de `metricasMlParams.test.js` (revertido el código para verlos fallar); GREEN = `pnpm test` 156 archivos / 2060 tests, lint 0 errores, lint:css limpio, build ok, `pnpm test:visual` 10 archivos / 84 passed (+2 expected fail preexistentes; 4 tests visuales nuevos 1920/1366 x claro/oscuro: controles en una línea, sin overflow de celdas, dinero y conteos sin wrap, columna fija). El test de "Reintentar" tras fallar una página se escribió junto con el código (sin RED separado).
- T6 medición (Postgres local, fixture de volumen 2.000 productos / 6.000 publicaciones / 81.000 grupos de órdenes, 30 días, `-s`): vista agrupada = 19 sentencias por request en las 5 dimensiones y con página de 10 o 200 (igual que la vista Productos), ~720-760 ms (Productos: ~660 ms; el grueso, igual que allí, son las dos tablas temporales ~430 ms); sus 3 sentencias propias: conteo de grupos ~2 ms, página ~12-15 ms, series ~25-30 ms. Con filtros (marca+estado+solo con ventas) ~670 ms. Abrir un grupo (100 de 800 productos): 10 sentencias, ~565 ms (con filtros de fila ~620 ms). Antes de mover la clave a la tabla de pares el mismo despliegue tardaba 3,8-4,4 s.
- Suite backend completa por tandas (ENVIRONMENT=testing, `-p no:randomly`): 8110 passed, 16 skipped (8126 colectados). `ruff format --check app/ tests/` y `ruff check app/` limpios.
- T7 observaciones de la revisión (todas corregidas): R4-001 RED = el "Ver más" con una segunda página que repite una fila duplicaba la clave (test de overlap); GREEN = `appendNew` descarta filas ya cargadas; el ORDER BY ya cierra con la clave única del producto (test de paginado con empates). R2-001 `_has_row_filters` se deriva de `ROW_AXES` (+ sus `_exclude`) y `solo_con_ventas`; test por cada eje. R2-002 `dimension_of` recibe columnas explícitas (sin el stand-in). R2-003 RED = faltaban `STORE_KEY_PREFIX`/`CLAVE_KEY_PREFIX`; GREEN = constantes usadas al codificar y al leer (`substr`). R2-004 estado `publications` -> `subRows` (página y tabla). R2-005 `_csv_line` único con cabeza por layout y cola compartida; el layout se elige una vez (`keys_of`/`rows_of`); test de cola compartida. R2-006 `DIMENSION_HEADERS` con `assert` contra `board.DIMENSIONS` + test. R3-001 test parametrizado sobre todos los `SORTS` x asc/desc en el tablero agrupado y en group-products: todos 200 (ninguno hace falta rechazarlo). R3-002 RED = la fila de grupo mostraba INMOVILIZADO/PÉRDIDA; GREEN = `GroupCell` sin badges y `_row_out` devuelve `alerts=[]` en grupos (test backend y frontend).
  Checks: pytest ml_daily_metrics + routers + board = verde; ruff format/check limpios; `pnpm test` 2062 passed; lint 0 errores; lint:css ok; build ok; test:visual 84 passed (+2 expected fail).
- T7b (GGA, push): RED = la misma fila de producto bajo dos grupos abiertos repetía la clave React `sub-<producto>`; GREEN = la clave de la sub-fila incluye la fila padre (`sub-<grupo>-<producto>`).
- T7c (GGA, observaciones con PASS): RED = tras descartar una fila repetida, la página siguiente pedía offset desfasado; GREEN = se cuenta lo que devolvió el servidor (`fetched`) aparte de las filas mostradas. El `assert` de `DIMENSION_HEADERS` pasa a `raise RuntimeError` (sobrevive a `python -O`).
