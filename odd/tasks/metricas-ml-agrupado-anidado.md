# Métricas ML — vista "Agrupado" anidada (niveles)

## Objetivo

El "Agrupado" de Métricas ML pasa de UN nivel de grupos (cada uno con una lista plana de
productos) a un ÁRBOL: cada dimensión se despliega en sus niveles hasta el producto.

## Problema (feedback del usuario, textual)

"el agrupado de métricas no está tan correcto, categorías y sub categorías tendrían que
estar nested, los productos como una capa después de la sub categoría dentro de la
categoría, hay que hacer más niveles en la tabla, porque sino el desglose no se aprecia,
si yo busco notebook y quiero ver de que subcategoría son las ventas no puedo, y las
subcategorías persé son un desastre para ubicar a que categoría pertenece cada una y marca
también, si se puede separar pero el desglose tiene que estar nested, sino no tiene
sentido, PMs lo mismo el desglose tiene que ser marca>categoría>subcategoría>producto. no
todos los productos sueltos."

## Jerarquía confirmada por el usuario

| Agrupar por | Niveles |
|---|---|
| Categoría | Categoría › Subcategoría › Producto |
| Subcategoría | Subcategoría (rotulada con su categoría, p. ej. "Notebooks · Computación") › Producto |
| Marca | Marca › Categoría › Subcategoría › Producto |
| PM | PM › Marca › Categoría › Subcategoría › Producto |
| Tienda | Tienda › Marca › Categoría › Subcategoría › Producto |

## Medición: de dónde sale la "categoría" (ANTES de codificar)

Opciones: `productos_erp.categoria` (la usan el filtro de categoría y la regla de PM
marca+categoría) o `subcategorias_grupos.nombre_categoria` (el grupo de la subcategoría).
SQL de la medición (de sólo lectura, para correr en producción):
`odd/sql/metricas-ml-categoria-source.sql`.

Resultado en la base local `pricing_dev` (3.828 productos, 280 subcategorías):

- 3.828 productos con categoría y con subcategoría; 0 con subcategoría y sin categoría.
- Subcategorías cuyos productos caen en más de una `productos_erp.categoria`: **0**.
- Productos cuya `productos_erp.categoria` difiere de `subcategorias_grupos.nombre_categoria`
  de su subcategoría (sin mayúsculas ni espacios): **0**.
- Productos con `subcategoria_id` sin fila en `subcategorias_grupos`: 3 (se muestran como
  "Subcategoría #<id>", igual que hoy).

Resultado en PRODUCCIÓN (corrido por el usuario, 2026-10-06, mismo SQL): 4.371 productos, todos
con categoría y con subcategoría (0 con subcategoría y sin categoría); subcategorías que
mapean a más de una `productos_erp.categoria`: **0**; productos cuya categoría difiere de la
de su subcategoría: **0**; productos con `subcategoria_id` sin fila en `subcategorias_grupos`:
18 (se muestran como "Subcategoría #<id>"). Decisión confirmada.

Decisión: la jerarquía usa `productos_erp.categoria` (consistente con el filtro de
categoría y la regla de PM). El árbol no se rompe en los datos medidos. Si en producción una
subcategoría tuviera productos en varias categorías, aparece DEBAJO DE CADA una (el nodo se
identifica por la ruta: categoría + subcategoría), y en la dimensión Subcategoría el nodo
se identifica por (subcategoría, categoría) y se rotula "Subcategoría · Categoría".

## Decisiones de diseño

- No hay tablas nuevas. Misma base de siempre (tablas TEMPORARY del request). La clave y la
  etiqueta de CADA nivel de la ruta son columnas de la tabla de pares (`gk0..gkN`/`gl0..glN`);
  `groups.py` pasa de una dimensión a un CAMINO de niveles (`HIERARCHIES`).
- Un nodo se identifica por la RUTA de claves de sus ancestros. Abrir un nodo = una página del
  nivel siguiente (`gk0=.. AND gk1=..`, agrupando por `gk<n>`); en el último nivel son los
  productos (mismo mecanismo que hoy).
- Cada nivel: mismas columnas de métricas; markup = SUM(gauss)/SUM(costo) del nodo; stock =
  suma de productos distintos; orden único para todos los niveles, paginado estable
  (orden + clave única) con "Ver más" y deduplicado en el frontend.
- Búsqueda y filtros se aplican ANTES de agregar: sólo existen las ramas con productos que
  coinciden. Los filtros de fila se deciden por producto entero (como hoy).
- "Sin X" en cada nivel. Tienda por `clave`; las ventas de un producto se parten por tienda y
  la invariante se mantiene hasta el producto.
- API: `GET /board?group_by=group&dimension=` devuelve los nodos del nivel 0 (+ `levels`);
  `GET /board/group-nodes?path=<JSON de claves>` devuelve el nivel siguiente (o los productos);
  reemplaza a `group-products` (la UI es el único consumidor).
- CSV agrupado: una fila por producto hoja con las columnas de la ruta completa; claves fijas
  y ordenadas, guarda de fórmulas, tope. Con "solo con ventas" no se exportan hojas sin unidades.
- Permisos sin cambios (ver_ganancia en cada nivel).

## Alcance autorizado

`backend/app/services/ml_daily_metrics/{board,groups}.py`, `routers/ml_metricas.py` y sus
tests; `frontend/src/pages/MetricasML.jsx`, `components/metricasMl/*`, `utils/metricasMl*`,
vitest y visual. No se toca Ventas ML ni Productos. Sin migraciones.

## Modo de pruebas

Strict TDD: habilitado (instrucciones del proyecto/usuario; RED observado antes de cada
GREEN). Runners: backend `pytest` (SQLite + `@pytest.mark.postgres` con `POSTGRES_TEST_URL`),
frontend `pnpm test` (vitest) y `pnpm test:visual`.

## Ruta por tarea

Todas: un writer (este agente). Tareas con 2+ archivos no triviales.

## Tareas

- [x] T1 Servicio: jerarquía de niveles (`groups.py`) y nodos de cualquier profundidad (`Board(scope=)`): Sin X, ruta, tienda, búsqueda, orden, paginado, conciliación por nivel.
- [x] T2 Servicio: hojas para el CSV (una fila por producto con la ruta) y techo de sentencias por nivel.
- [x] T3 Router: `levels`, `group-nodes`, CSV con ruta, permisos, techo.
- [ ] T4 Frontend: árbol de niveles (carga perezosa, paginado por nivel, indentación), vitest.
- [ ] T5 Visual (`test:visual`) de los estados anidados.
- [ ] T6 Medición en el fixture de volumen + verificación completa + push.

## Criterios de aceptación

1. Las 5 dimensiones despliegan en los niveles de la tabla de arriba, hasta el producto.
2. Los hijos suman al padre en cada nivel (unidades y facturado exactos; Gauss <= 1 centavo por nodo).
3. Buscar "notebook" deja sólo las ramas con esos productos.
4. "Sin X" en cada nivel; tienda por clave con la venta partida por tienda hasta el producto.
5. Cada nivel está paginado y estable; el orden vale para todos los niveles.
6. CSV: una fila por producto con la ruta completa.
7. Sentencias por request acotadas (techo con test); sin tablas nuevas.
8. Sin ver_ganancia no hay márgenes en ningún nivel.

## Verificación

pytest (tests tocados + `pytest tests -q`), `ruff format --check app/ tests/`, `ruff check app/`,
`pnpm test -- --run`, `pnpm lint`, `pnpm lint:css`, `pnpm build`, `pnpm test:visual`.

## Progreso / evidencia

- T0 medición: ver arriba (0 conflictos en `pricing_dev` ni en producción).
- T1 (`7b1303eb`): RED = `AttributeError: module 'groups' has no attribute 'levels_of'` (todo el archivo `test_board_nested_groups_postgres.py` nuevo falla); GREEN = 38 tests: tabla de niveles por dimensión, nodos a cualquier profundidad (categoría>sub, marca>cat>sub, PM, tienda por clave con la venta partida hasta el producto, Subcategoría rotulada con su categoría y partida por categoría), "Sin X" profundos, conciliación recursiva (hijos = padre por nivel en las 5 dimensiones; unidades/facturado/costo exactos, Gauss <= 1 centavo por nodo), búsqueda y filtros por producto antes de agregar, orden por nivel, paginado estable con empates, ruta desconocida. Hallazgo: `scope_keys` (CTE de sobrevivientes) se instanciaba dos veces en una sentencia -> `CompileError: Multiple, unrelated CTEs`; arreglo: un único CTE por Board. Los tests del tope plano de `test_board_groups_postgres.py` se actualizaron (clave `<id>|<categoría>`); su sección "abrir grupo -> productos" la reemplaza la conciliación recursiva.
- T2: RED = `AttributeError: 'Board' object has no attribute 'leaf_keys'` (12 tests); GREEN = 62 tests del archivo: hojas = una fila por (ruta, producto) con los nombres de la ruta, suman a los KPIs en las 5 dimensiones, un producto en dos tiendas = una hoja por tienda con sus ventas, orden = ruta y luego el orden del tablero, fetch por clave en el orden pedido (salta la desaparecida), tope, filtros / "solo con ventas" / stock. Techo de sentencias de una página de nivel (profundidades 0..4, con y sin filtros de fila): <= 12 (test que fija el número; no hizo falta tocar el código para cumplirlo, porque todos los niveles comparten el camino de la tabla de pares).
- T3: RED = 22 de 37 tests de router fallan (sin `levels`/`level`, 404 en `/board/group-nodes`, CSV con filas de grupo); GREEN = 37 tests de `test_ml_metricas_board_groups_router.py` + `test_ml_metricas_board_router.py` + `tests/services/ml_daily_metrics` = 329 passed. API: `GET /board?group_by=group&dimension=` devuelve los nodos del nivel 0 + `levels`; `GET /board/group-nodes?path=<JSON list de claves>&limit&offset` devuelve el nivel siguiente (`level`, `rows`, `total`) o los productos en el último nivel; reemplaza a `group-products` (se eliminó: la UI es el único consumidor). `path` inválido (no JSON, vacío, demasiado largo, no-texto) = 422. CSV agrupado: una fila por producto con las columnas de la ruta (`LEVEL_HEADERS`; "Marca" propia sólo si la ruta no la trae), claves fijas con `Board.leaf_keys` + `leaves_for_keys`, guarda de fórmulas en cada nombre de la ruta, tope `EXPORT_MAX_ROWS`. Permisos: sin `ver_ganancia`, ningún nivel trae márgenes y ordenar por margen en `group-nodes` es 403 (test sobre nodos y productos).
