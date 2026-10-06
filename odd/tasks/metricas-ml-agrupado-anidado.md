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

- [ ] T1 Servicio: jerarquía de niveles (`groups.py`) y nodos de cualquier profundidad (`Board(scope=)`): Sin X, ruta, tienda, búsqueda, orden, paginado, conciliación por nivel.
- [ ] T2 Servicio: hojas para el CSV (una fila por producto con la ruta) y techo de sentencias por nivel.
- [ ] T3 Router: `levels`, `group-nodes`, CSV con ruta, permisos, techo.
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

- T0 medición: ver arriba (0 conflictos en `pricing_dev`).
