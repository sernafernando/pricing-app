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

- [x] T1 Mapear el comportamiento real de los filtros en Productos antes de copiar nada:
      de dónde salen las opciones, cómo se busca dentro del panel, y cómo el PM
      seleccionado angosta las marcas ofrecidas (`marcasPorPM`). Reportar lo que se
      encuentre; no suponer.
- [x] T2 RED: la pantalla no ofrece filtro de marca / subcategoría / PM.
- [x] T3 GREEN: componente compartido + su hook de estado, autocontenido.
- [x] T4 RED/GREEN: seleccionar un filtro manda el CSV correcto a `/sales`.
- [x] T5 RED/GREEN: los tres conviven, y el botón de limpiar también los limpia.
- [x] T6 RED/GREEN: round-trip por URL, con el mismo patrón que ya usan los filtros
      existentes de la pantalla (no inventar uno nuevo).
- [x] T7 Verificar que los conteos de los chips existentes siguen coincidiendo con lo que
      muestra la tabla cuando hay un filtro de producto activo.
- [x] T8 Verificación por mutación de cada test nuevo.

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

## Tareas de corrección (post-mapeo del componente compartido)

- [x] T9 Verificar la afirmación del JSDoc sobre "clases globales compartidas": es falsa, esas
      clases (`filter-button`, `advanced-filters-panel`, `dropdown-*`, ...) solo existen en el
      CSS de `Productos.jsx`/`Tienda.jsx`/`ItemsSinMLA.jsx`, cargado de forma diferida — el
      panel se ve sin estilos si Ventas ML se abre directo.
- [x] T10 `ProductFiltersPanel.module.css` — mismo aspecto visual que `Productos.css`, pero
      sobre tokens de `styles/theme.css` (claro y oscuro), sin ningún valor hardcodeado
      (ratchet `css-guard/cssGuard.test.js` en verde).
- [x] T11 JSDoc corregido: ya no afirma reuso de clases globales inexistentes.
- [x] T12 Cierre del dropdown con clic afuera y con Escape, sin pisar el Escape de
      `VentasMLLayout` (detalle de venta).
- [x] T13 `useProductFilters.js`: import único de `services/api`, limpieza de líneas en blanco.

## Progreso

- 2026-09-28 — Documento creado tras confirmar que el backend está completo y sin consumidor.
- 2026-09-28 — Implementado y verificado. Componente `ProductFiltersPanel.jsx` + hook
  `useProductFilters.js` (ambos en `frontend/src/{components/shared,hooks}/`, autocontenidos,
  sin import desde `ventasMl/`). Cableado en `VentasML.jsx`; round-trip por URL agregado a
  `useVentasMLFilters.js` (mismo patrón CSV que ya usaba `q`). `facet_base` del backend ya
  incluía marcas/subcategorías/pms desde PR9 (verificado, no hizo falta tocarlo). Tests:
  `useVentasMLFilters.productFilters.test.jsx` (4) y `VentasML.productFilters.test.jsx` (2),
  cada uno verificado por mutación ejecutada (rojo confirmado, revertido). Suite completa
  (1738 passed) y `pnpm build` en verde. `/sales/kpis` no se llama hoy desde `VentasML.jsx`;
  quedó listo para cuando llegue (mismos params). Deuda declarada sin cambios.
- 2026-09-28 — Corrección post-review: `ProductFiltersPanel.module.css` nuevo (tokens de
  `theme.css`, claro/oscuro, sin hardcodear), JSDoc corregido, cierre con clic afuera/Escape
  sin pisar el Escape de `VentasMLLayout` (Escape se registra UNA sola vez al montar —no en
  cada apertura del dropdown— para que el listener de este componente, hijo de
  `VentasMLLayout`, quede siempre registrado antes que el de `VentasMLLayout`, y
  `preventDefault()` evita que el Escape del dropdown también cierre el panel de detalle),
  y limpieza de `useProductFilters.js` (import único + líneas en blanco). 4 tests nuevos en
  `ProductFiltersPanel.test.jsx`, cada uno con rojo confirmado (mutación ejecutada revirtiendo
  `preventDefault`, restaurado luego). Suite completa (1743 passed + 2 expected fail),
  `pnpm build` y `css-guard/cssGuard.test.js` en verde. No se pudo verificar apariencia visual
  real (jsdom corre con `css: false`, sin layout ni estilos computados) — se verificó por
  lectura de código que ningún className de página (`filter-button`,
  `advanced-filters-panel`, `dropdown-*`) sigue en uso.
