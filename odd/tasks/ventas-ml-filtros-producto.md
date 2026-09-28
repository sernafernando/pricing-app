# Filtros de producto en Ventas ML (marca / subcategoría / PM)

**Creado:** 2026-09-28 · **Estado:** en curso
**TDD:** estricto · **Runner:** `cd frontend && pnpm exec vitest run` (pnpm, nunca npm)
**Rama:** `feat/ventas-ml-filtros-producto`, salida de `origin/main`

## Problema

El backend de estos filtros está COMPLETO desde PR9 (spec `ml-sales-product-filters`,
R35-R39, con tests): `SalesFilter` acepta `marcas`, `subcategorias` y `pms`; el endpoint
`GET /sales` los recibe como CSV; `build_scope` los aplica reusando la misma resolución de
pares marca+categoría que `productos_listing.py`.

**No hay UI que los use.** `VentasML.jsx` manda exactamente cinco parámetros:
`operation_status`, `goods_status`, `date_from`, `date_to`, `q`. Cero referencias a los
filtros de producto. Ninguna tarea del plan SDD tomó el frontend: grep de `tasks.md` sobre
`marcas`/`subcategorias`/`pms` solo devuelve tareas de backend.

No se rompió: nunca se construyó. Capacidad de servidor sin consumidor.

## Por qué un componente y no una copia

Esa UI ya está duplicada en CINCO lugares: `Productos.jsx`, `TabRentabilidad.jsx`,
`TabRentabilidadFuera.jsx`, `TabRentabilidadTiendaNube.jsx` y la carga de opciones en
`useTiendaData.js`. Agregar una sexta copia empeora el problema.

**Decisión del usuario:** hacer el componente compartido bien, pero **usarlo SOLO en
Ventas ML**. Las otras pantallas las migra él después. Así el código nuevo nace limpio y el
radio de impacto hoy es cero.

## Alcance autorizado

- Componente nuevo, autocontenido, para los tres filtros de producto.
- Cablearlo ÚNICAMENTE en Ventas ML.

**Fuera de alcance, explícito:** no se toca `Productos.jsx`, ni las tres pestañas de
Rentabilidad, ni `useTiendaData.js`. Ni siquiera para "aprovechar el viaje".

## Tareas

- [ ] T1 Mapear el comportamiento real de los filtros en Productos antes de copiar nada:
      de dónde salen las opciones, cómo se busca dentro del panel, y cómo el PM
      seleccionado angosta las marcas ofrecidas (`marcasPorPM`). Reportar lo que se
      encuentre; no suponer.
- [ ] T2 RED: la pantalla no ofrece filtro de marca / subcategoría / PM.
- [ ] T3 GREEN: componente compartido + su hook de estado, autocontenido.
- [ ] T4 RED/GREEN: seleccionar un filtro manda el CSV correcto a `/sales`.
- [ ] T5 RED/GREEN: los tres conviven, y el botón de limpiar también los limpia.
- [ ] T6 RED/GREEN: round-trip por URL, con el mismo patrón que ya usan los filtros
      existentes de la pantalla (no inventar uno nuevo).
- [ ] T7 Verificar que los conteos de los chips existentes siguen coincidiendo con lo que
      muestra la tabla cuando hay un filtro de producto activo.
- [ ] T8 Verificación por mutación de cada test nuevo.

## Criterios de aceptación

- Los tres filtros funcionan y viajan al backend.
- Ninguna de las otras cuatro pantallas cambia de comportamiento.
- El componente no depende de nada propio de Ventas ML: la próxima pantalla lo usa sin tocarlo.

## Deuda declarada

- Migrar Productos, las tres Rentabilidad y `useTiendaData` al componente nuevo. Lo hace el
  usuario, no este slice.
- El filtro de TIENDA OFICIAL queda fuera por decisión de spec (R36a): el store de una venta
  solo se puede leer de las publicaciones ACTUALES del producto, así que la misma venta
  entraría o saldría del filtro a medida que las publicaciones se mueven.

## Progreso

- 2026-09-28 — Documento creado tras confirmar que el backend está completo y sin consumidor.
