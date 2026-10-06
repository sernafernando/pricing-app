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
- [ ] T3 Ventas ML (backend): `categorias` en `/sales`, `/sales/export`, `/sales/kpis`; `facets.product` simétrico incl. tienda, tests Postgres + router.
- [ ] T4 Frontend compartido: `ProductFiltersPanel` con Categoría y opciones del servidor (sin carga propia), tests vitest.
- [ ] T5 Frontend cableado: Métricas ML + Ventas ML (params `categorias`, `options` desde `facets.product`, limpiar filtros), tests vitest + visual.
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

