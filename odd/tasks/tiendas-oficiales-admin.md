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
- [ ] T3 Backend: helper `store_ids_for_clave` + dashboard TP-Link + sync/ingesta TP-Link por clave (fail-closed) + sin `2645` literal
- [ ] T4 Frontend: hook `useTiendasOficiales` + panel Admin
- [ ] T5 Frontend: consumidores (Ventas ML, Metricas ML, Productos, TreeNode, ExportModal, DashboardMetricasML) + limpieza de constantes

## Criterios de aceptacion

- Tras deploy nada cambia visualmente (seed identico).
- Admin puede crear/renombrar/reordenar/desactivar tiendas; sin permiso -> 403.
- Ningun consumidor usa el mapa hardcodeado; dashboard TP-Link y su sync usan los ids de la clave `tplink`.
- `alembic heads` = un solo head.

## Checks

pytest (nuevos + suite completa), ruff format/check, pnpm test, lint, build, test:visual si aplica.

## Progreso / evidencia

- T1: RED = test_migration_ml_tiendas_oficiales_postgres + test_ml_tienda_oficial (ImportError/2 failed por falta de `clave`); GREEN = 9 passed. Seed ampliado: 471846 (nuevo id TP-Link, clave tplink) orden 2; 471846 no aparecia en el codigo. T2: RED = 10 failed router + 1 failed items-sin-mla; GREEN = 11 + 1 passed. Sin DELETE a proposito (se desactiva). Nota: `ruff format alembic/` reformatea ~120 migraciones historicas ajenas (drift previo): se formatean solo archivos propios.

## Siguiente paso

T3
