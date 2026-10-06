# Filtros cruzados (categoría + facetas dinámicas) en Métricas ML y Ventas ML

## Objetivo

En Métricas ML y Ventas ML, las opciones de cada filtro (marca, categoría,
subcategoría, PM, tienda) se acotan por TODOS los demás filtros activos, en las
dos direcciones, y existe el filtro de categoría. Pedido del usuario
(2026-10-05): "no está el filtro de categoría y los filtros no son dinámicos
como en la página productos, si yo elijo hoy una marca, no puedo elegir
categorías y tengo para elegir subcategorías que no son de la marca, así
también con el pm" + "el filtro cruzado también te falta en Ventas ML" + "al
revés también, no solo la marca acota, todo acota entre sí".

## Problema

- Métricas ML y Ventas ML comparten `ProductFiltersPanel` / `useProductFilters`:
  cargan las listas completas (`/marcas`, `/subcategorias`, `/usuarios/pms`) una
  vez, y sólo acotan por PM (marcas/subcategorías de los PMs elegidos). Elegir
  una marca no acota nada; no existe categoría.
- Productos hace la cascada en el servidor (`/marcas?subcategorias=&pms=`,
  `/subcategorias?marcas=&pms=`), sólo marca <-> subcategoría <-> PM sobre el
  catálogo; no conoce tienda ni el universo de ventas del período.

## Decisiones

- "Categoría" = `productos_erp.categoria` (la misma que arma el par marca+categoría
  del PM, `marcas_pm`). Se filtra case-insensitive como la marca.
- Las opciones salen del UNIVERSO REAL de cada pantalla (filas del tablero / grupos
  de Ventas ML bajo todos los demás filtros: fechas, búsqueda, tienda, estado,
  stock, ageing...), no del catálogo entero: así tienda y período también acotan.
- Un helper compartido (`app/services/product_facets.py`) recibe las combinaciones
  distintas `(marca, categoria, subcategoria_id, pm_id)` del universo (UNA consulta
  set-based por pantalla) y calcula las 4 listas con la regla estándar: cada faceta
  = todos los filtros activos menos el suyo. Lo seleccionado siempre se ofrece
  (para poder destildarlo). La faceta de tienda ya se acotaba por los filtros de
  producto; el cambio es que ahora los filtros de producto también se acotan
  entre sí y por la tienda.
- Sin tablas derivadas: sólo tablas existentes (regla del proyecto). Medición en
  la tarea T6.
- Contratos de query-params compatibles: se agrega `categorias` (CSV de nombres)
  con `parse_csv_strings`; la respuesta agrega `facets.product` (aditivo).

## Alcance autorizado

`backend/app/services/product_facets.py` (nuevo), `ml_daily_metrics/board.py`,
`routers/ml_metricas.py`, `ml_sales_query/filters.py`, `routers/ml_ventas_ops.py`,
sus tests; `frontend/src/components/shared/ProductFiltersPanel*`,
`hooks/useProductFilters*`, `pages/MetricasML.jsx`, `pages/VentasML.jsx`,
`hooks/useVentasMLFilters.js`, `utils/metricasMlParams.js`, params de Ventas ML.
No se toca Productos ni los nombres de tienda (otra rama).

## Modo de pruebas

Strict TDD: habilitado (fuente: instrucciones del proyecto/usuario). Runners:
backend `pytest` (SQLite + `@pytest.mark.postgres` contra `POSTGRES_TEST_URL`),
frontend `pnpm test` (vitest, proyecto unit) y `pnpm test:visual`.

## Ruta por tarea

Todas: delegated direct (un writer). Evidencia del trigger: toca 2+ archivos no
triviales por tarea.

## Tareas

- [x] T1 Helper compartido `product_facets` (cascada simétrica, selección siempre visible, nombres de subcategoría/PM). Tests unitarios + resolución de nombres.
- [x] T2 Tablero (backend): filtro `categorias`, `facets.product` simétrico incl. tienda/filas, tests Postgres + router.
- [x] T3 Ventas ML (backend): `categorias` en `/sales`, `/sales/export`, `/sales/kpis`; `facets.product` simétrico incl. tienda, tests Postgres + router.
- [x] T4 Frontend compartido: `ProductFiltersPanel` con Categoría y opciones del servidor (sin carga propia), tests vitest.
- [x] T5 Frontend cableado: Métricas ML + Ventas ML (params `categorias`, `options` desde `facets.product`, limpiar filtros), tests vitest + visual.
- [ ] T6 Medición EXPLAIN ANALYZE + verificación completa.

## Criterios de aceptación

1. Elegir marca: categorías, subcategorías y PMs ofrecidos son sólo los de la marca.
2. Direcciones inversas: subcategoría -> marcas/categorías/PMs/tiendas; PM -> marcas/categorías/subcategorías/tiendas; tienda -> marcas/categorías/subcategorías/PMs; categoría -> marcas/subcategorías/PMs/tiendas.
3. La faceta propia no se acota por sí misma.
4. Mismo comportamiento en Métricas ML y Ventas ML.
5. `categorias` filtra tablero, sub-filas, export CSV y KPIs de Ventas.
6. Sin regresión de contratos existentes.

## Verificación

pytest (tests tocados + `pytest tests -q`), `ruff format --check app/ tests/`,
`ruff check app/`, `pnpm test`, `pnpm lint`, `pnpm lint:css`, `pnpm build`,
`pnpm test:visual`.

## Progreso / evidencia

- T1 (c57979db, rehecho en T2): RED = ImportError (módulo inexistente); GREEN = 10 tests `test_product_facets.py`. El helper terminó en dos piezas: `product_combo_rows` (UNA sentencia: combinaciones distintas del universo + nombres de subcategoría + pares PM/nombres por LEFT JOIN) y `product_facet_options` (cascada en memoria).
- T2 (commit al cerrar T2): RED = 11 tests de router fallaban (sin `facets.product` ni `categorias`); GREEN = 11 router (SQLite) + 1 Postgres (`test_board_product_facets_postgres.py`). Techo de sentencias del tablero (volumen, <=19) se mantiene: +1 sentencia (19 con página llena, 17 vacía).

- T3 (commit al cerrar T3): RED = 16 tests de router fallaban (`categorias` ignorado, sin `facets.product`); GREEN = 16 router (SQLite) + 1 Postgres (`test_ventas_product_facets_postgres.py`, incluye pack). Universo = grupos del listado con los filtros de producto limpios (estado, switches, tienda, búsqueda, período incluidos) + hermanos del pack; ítems vía costo congelado. Presupuesto de queries del listado (`ml_order_item_costos` <= 2) actualizado: la lectura de opciones suma UNA sentencia constante.
- T4+T5 (un solo commit frontend: el panel sin carga propia deja las dos pantallas rotas hasta cablearlas, y un commit intermedio en rojo no es entregable): RED = panel (ImportError del mock que prohíbe cargar opciones propias), params (`categorias`), URL de Ventas, 5 tests de VentasML y 3 de MetricasML; GREEN = `pnpm test` 1997 passed, `pnpm lint` 0 errores, `pnpm lint:css` limpio, `pnpm build` ok, `pnpm test:visual` 80 passed (+2 expected fail preexistentes). Captura de la franja PRODUCTO con 4 botones revisada (cabe sin wrap en 1366).
- T6 medición, CORREGIDA tras review (volumen del test: 2.000 productos / 6.000 publicaciones / 81.000 grupos; Postgres local 18; segunda corrida de cada medición, timers independientes): opciones del tablero = 1 sentencia, `Execution Time` 21 ms (35 combinaciones); tablero entero 19 sentencias (techo <=19 intacto). Ventas, 30 días (~6,7k grupos): sin faceta activa, la sentencia de combinaciones sola ~207 ms (EXPLAIN 266 ms); con faceta activa (marcas=Epson: segundo `build_scope` + sentencia) ~211 ms; `build_scope` solo ~2 ms (arma la query, no la ejecuta); chips de tienda existentes sobre el mismo scope ~339 ms. Las cifras anteriores (332 ms "opciones") eran la medición de `store_facet_counts` por un timer pisado. Sin volumen realista de `marcas_pm`/`subcategorias_grupos` local (pricing_dev: 3.828 productos, 355 pares): se sembraron 355 pares y 400 subcategorías en el test.
- Review R3 #1 (timers del test de volumen): RED = el print de opciones de Ventas medía `store_facet_counts`; arreglo = timers independientes, código muerto (`SELECT 1`) fuera, cubierto también el camino con faceta activa.
- Review R3 #2 (frontend, selección vs servidor): RED = 5 tests (misma selección con otra capitalización duplicada y sin tildar; subcategoría/PM seleccionados invisibles antes de la respuesta o si falla); GREEN = comparación case-insensitive con la grafía del servidor como canónica (destildar con cualquiera de las dos grafías), y fallback `Subcategoría #id` (grupo "Seleccionadas") / `PM #id` para ids seleccionados sin nombre a mano. `pnpm test` 2002 passed, lint 0 errores, lint:css limpio, build ok, test:visual 80 passed (+2 expected fail preexistentes).
- Suite backend completa (antes de estos arreglos): 7986 passed, 16 skipped, 1 fallo `tests/smoke/test_health.py::test_openapi_schema_loads` que es del entorno (docs deshabilitados sin ENVIRONMENT=development; con `ENVIRONMENT=development` pasa).
