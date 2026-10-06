# Tiendas oficiales administrables desde el panel Admin

## Objetivo

Definir el nombre (y orden / estado) de cada tienda oficial de MercadoLibre por
`official_store_id` desde el panel Admin, en lugar de tenerlo hardcodeado.

## Problema

Los nombres viven en `frontend/src/constants/tiendasOficiales.js` y duplicados en
`backend/app/api/endpoints/items_sin_mla.py` (`TIENDAS_OFICIALES`) y en
`ExportModal.jsx`. Agregar o renombrar una tienda exige un deploy.

## Alcance autorizado

- Tabla `ml_tiendas_oficiales` (store_id PK, nombre, orden, activa, timestamps) +
  migracion Alembic con seed de las 4 tiendas actuales y permiso
  `admin.tiendas_oficiales` (ADMIN).
- Backend: modelo, schemas, router `GET /api/tiendas-oficiales` (autenticado) y CRUD
  admin gateado por permiso. `/items-sin-mla/tiendas-oficiales` pasa a leer la tabla.
- Frontend: seccion en Admin, hook `useTiendasOficiales` (`getLabel(id)`), reemplazo
  en Ventas ML, Metricas ML, Productos, TreeNode, ExportModal, ItemsSinMLA.
- CAMBIO DE ALCANCE (usuario): el dashboard TP-Link TAMBIEN cambia, porque cambio el
  ID de la tienda TP-Link en ML. Columna `clave` (slug, NO unica) en la tabla; 2645
  sembrado con `tplink`; el backend resuelve los ids de TP-Link por clave (incluye
  inactivas) y falla cerrado si no hay ninguno. Sin `2645` literal en codigo de app.

## Constraints / config

- TDD: strict. Runners: pytest (backend), vitest (frontend).
- Heuristica ~400 lineas por tarea (solo planificacion).
- Desconocido -> `Tienda <id>`; null -> comportamiento actual ("Sin tienda").
- Contrato de params de filtro (`stores`) sin cambios.

## Tareas

- [x] T1 (f3e879c6, f22142d1) Backend: tabla (con `clave`) + modelo + migracion (seed + permiso) + tests
- [x] T2 Backend: schemas + router GET/CRUD (con `clave`) + permiso + `items-sin-mla` desde tabla
- [x] T3 Backend: helper `store_ids_for_clave` + dashboard TP-Link + sync/ingesta TP-Link por clave (fail-closed) + sin `2645` literal
- [x] T4 Frontend: hook `useTiendasOficiales` + panel Admin
- [x] T5 Frontend: consumidores (Ventas ML, Metricas ML, Productos, TreeNode, ExportModal, DashboardMetricasML) + limpieza de constantes

## Criterios de aceptacion

- Tras deploy nada cambia visualmente (seed identico).
- Admin puede crear/renombrar/reordenar/desactivar tiendas; sin permiso -> 403.
- Ningun consumidor usa el mapa hardcodeado; dashboard TP-Link y su sync usan los ids de la clave `tplink`.
- `alembic heads` = un solo head.

## Checks

pytest (nuevos + suite completa), ruff format/check, pnpm test, lint, build, test:visual si aplica.

## Progreso / evidencia

- T1: RED = test_migration_ml_tiendas_oficiales_postgres + test_ml_tienda_oficial (ImportError/2 failed por falta de `clave`); GREEN = 9 passed. Seed ampliado: 471846 (nuevo id TP-Link, clave tplink) orden 2; 471846 no aparecia en el codigo. T2: RED = 10 failed router + 1 failed items-sin-mla; GREEN = 11 + 1 passed. Sin DELETE a proposito (se desactiva). T3: RED = ImportError (service) + 3 failed dashboard/sql tests; GREEN = tplink/tiendas/metricas/items_sin_mla subset 276 passed. Dashboard `operaciones` fail-closed 503; scripts de ingesta usan `IN :store_ids`; `mlp_official_store_id` guarda el id real de la orden. Backfill necesario tras deploy: ver reporte final. T4: RED = vitest 'no tests' por import inexistente (hook y panel); GREEN = 7 hook + 5 panel passed. Tab 'Tiendas Oficiales' en Admin (sin gating de permiso en la tab: el backend responde 403). T5: RED = 9 failed (chips builder, Ventas/Metricas chips, TreeNode, Productos CS-11); GREEN = suite unit 1995 passed, lint 0 errors, build ok, test:visual 80 passed. ExportModal: test escrito despues del codigo (desvio de TDD, pasa y fallaria contra el codigo viejo). DashboardMetricasML tambien pasa a nombres/ids dinamicos. Emoji y tooltip del select de Productos se eliminan (la tabla no los guarda). Nota: `ruff format alembic/` reformatea ~120 migraciones historicas ajenas (drift previo): se formatean solo archivos propios.

- T6 (correccion pedida): tiendas con la misma `clave` colapsan en UNA opcion en todos los pickers (`groupStores`/`buildStoreChips`): ids de la clave incluidos los inactivos como CSV, etiqueta = primera activa por orden, conteo = suma, activa si todos sus ids estan seleccionados. RED = 16 failed; GREEN = unit 2005 passed, lint 0 errors, build ok, test:visual 80 passed. Metricas ML no agrega chips por facet (solo grupos activos).

- T7 (observaciones de review, todas corregidas):
  - R3-003 productos `tienda_oficial`: el parser ya aceptaba CSV; test nuevo old+new id (2645,471846 trae ambos) y parser; basura = 400 (contrato existente, no se cambia). Caracterizacion, sin RED posible.
  - R3-004 Ventas/Metricas `stores`: parsers ya aceptaban CSV; tests via router real (listado, facets, kpis, export; metricas board + export; basura 422). Caracterizacion, sin RED. Comentario de ventasMlParams.js actualizado.
  - R3-005 `mlp_official_store_id`: RED = test "fila sin la columna debe fallar" (DID NOT RAISE); GREEN al quitar el getattr default; test del SELECT; helpers de tests de fold con la columna.
  - R3-002 ExportModal: RED = hook getLabelForIds + display del filtro (2 failed); GREEN con `labelForIds`; Dashboard lo reutiliza.
  - R3-001 ItemsSinMLA.css: RED = test de selectores (2 failed); GREEN con el prefijo light en ambas reglas.
  - R3-006 crear tienda: RED = 500 en carrera; GREEN = IntegrityError -> rollback -> 409.
  - Verificacion: backend completo con ENVIRONMENT=testing 7995 passed, 0 failed; frontend 2009 passed, lint 0 errores, lint:css ok, build ok, test:visual 80 passed.

- T8 (observaciones GGA): docstring de la migracion (cinco filas); Dashboard cuenta tiendas con `labelsForIds` (RED = nombre con coma inflaba el conteo); ExportModal reindentado; URL legacy `tienda_oficial=2645` mapea a la opcion del grupo con `groupValueForSelection` (RED en el helper; el test de Productos CS-12 se escribio junto con el fix). unit 2014 passed, lint 0 errores, lint:css ok, build ok, migracion 6 passed.

## Siguiente paso

Entregar (sin push)
