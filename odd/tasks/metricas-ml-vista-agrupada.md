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

- [ ] T1 Servicio: filas agrupadas por dimensión (SQL set-based sobre los pares), 5 dimensiones, "Sin X", clave de tienda, markup como razón de sumas, conciliación con KPIs. Tests Postgres.
- [ ] T2 Servicio: despliegue de un grupo a sus productos (scope por grupo) + conteo/KPIs de grupos + techo de sentencias.
- [ ] T3 Router: `group_by=group&dimension=`, respuesta, endpoint de productos del grupo, export CSV agrupado, permisos. Tests de router.
- [ ] T4 Frontend: params, selector de dimensión, vista Agrupado (tabla, orden, KPIs), vitest.
- [ ] T5 Frontend: despliegue a productos, export, estado visual (`test:visual`).
- [ ] T6 Medición en el fixture de volumen + verificación completa.

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

(se completa por tarea)
