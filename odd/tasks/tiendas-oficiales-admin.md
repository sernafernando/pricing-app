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
- Fuera de alcance: dashboard TP-Link (store 2645 fijo a proposito).

## Constraints / config

- TDD: strict. Runners: pytest (backend), vitest (frontend).
- Heuristica ~400 lineas por tarea (solo planificacion).
- Desconocido -> `Tienda <id>`; null -> comportamiento actual ("Sin tienda").
- Contrato de params de filtro (`stores`) sin cambios.

## Tareas

- [ ] T1 Backend: tabla + modelo + migracion (seed + permiso) + test de migracion
- [ ] T2 Backend: schemas + router GET/CRUD + permiso + `items-sin-mla` desde tabla
- [ ] T3 Frontend: hook `useTiendasOficiales` + panel Admin
- [ ] T4 Frontend: consumidores (Ventas ML, Metricas ML, Productos, TreeNode, ExportModal) + limpieza de constantes

## Criterios de aceptacion

- Tras deploy nada cambia visualmente (seed identico).
- Admin puede crear/renombrar/reordenar/desactivar tiendas; sin permiso -> 403.
- Ningun consumidor usa el mapa hardcodeado.
- `alembic heads` = un solo head.

## Checks

pytest (nuevos + suite completa), ruff format/check, pnpm test, lint, build, test:visual si aplica.

## Progreso / evidencia

(se completa por tarea)

## Siguiente paso

T1
