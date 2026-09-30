# Ventas ML — columnas configurables (anchos desde config + selector)

## Objetivo

Que la tabla se entienda en una notebook y que el usuario elija qué columnas
ver, en vez de que el ancho lo decida un porcentaje hardcodeado en el CSS.

## Problema (medido, no estimado)

Los once anchos viven en clases CSS de `VentasML.module.css`. Las diez
columnas con porcentaje suman 83%, `colAlerta` son 32px fijos, y
`colProducto` está en `auto`: cobra las sobras. O sea que **la columna que
más espacio necesita es la única sin ancho garantizado.**

Con la sidebar expandida (240px, `--cf-sidebar-width-expanded`):

| Pantalla | Tabla | colProducto | Queda para el título |
|---|---|---|---|
| 1920 | ~1600 | 240px | ~172px (al filo: se desborda sobre Orden) |
| 1366 | ~1080 | 152px | **~84px** (ocho caracteres) |

Síntoma reportado: el contenido de Producto se derrama sobre la columna
Orden. No hay nada superpuesto en el CSS — ni márgenes negativos, ni
`position: absolute` — es desborde por celda angosta.

Y sobra ancho donde no hace falta. Medido contra el contenido real:

| Columna | Lo más largo que muestra | Necesita | Tiene (1600) |
|---|---|---|---|
| Mercadería | "Devuelto sin entregar" | ~153px | 176px |
| Operación | "Cubierta por ML" | ~114px | 144px |
| Importe / Neto | `$ 1.284.920,50` | ~110px | 144px |
| Total Gauss | idem | ~110px | 160px |

## Enfoque: el patrón que YA existe en este repo

`components/tn-reconcile/reconcileColumns.jsx` + `ReconcileTable.jsx` +
`pages/tiendaNubeReconcileTableHelpers.js`. `@tanstack/react-table` v8 ya es
dependencia y ya está en producción ahí.

Clave, del comentario del helper: *"the table instance is used only for
column sizing/resize; the body renders manually"*. TanStack se usa como
motor de GEOMETRÍA de columnas, no de filas. **No se porta la expansión del
pack**: las filas hijas se siguen renderizando a mano.

## Alcance autorizado

- Nuevo `frontend/src/components/ventasMl/ventasMlColumns.jsx` — el array
  `COLUMNS` (`{ id, header, size, cell }`), única fuente de verdad de header
  y body.
- Nuevo `frontend/src/components/ventasMl/ColumnPicker.jsx` + CSS module.
- Nuevo `frontend/src/pages/ventasMlTableHelpers.js` — persistencia
  fail-safe de VISIBILIDAD (el sizing no se implementó: los `size` son
  proporciones fijas, no hay resize por el usuario todavía), calcada de
  `tiendaNubeReconcileTableHelpers.js`.
- `frontend/src/pages/VentasML.jsx` y su CSS module.
- NADA de backend. NADA de la tira de KPIs que acaba de aterrizar.

## Tareas

- [x] T1 — `COLUMNS` con los once `{id, header, size, cell}` en
      `frontend/src/components/ventasMl/ventasMlColumns.jsx`. Tamaños en
      píxeles según la medición del doc: producto 320, orden 120, fecha 90,
      comprador 130, operación 120, mercadería 155, envío 110, importe 115,
      neto 115, total gauss 120, alerta 32.
- [x] T2 — `<colgroup>` desde `table.getVisibleLeafColumns()` con
      `col.getSize()` en `VentasML.jsx`. Los diez `.col*` de ancho-solo
      salieron de `VentasML.module.css` (queda `.colAlerta` sin `width`,
      solo centrado/nowrap).
- [x] T3 — El body del grupo renderiza iterando `visibleColumns` y llamando
      `def.cell(groupCtx)`.
- [x] T4 — Las filas hijas del pack iteran el MISMO `visibleColumns` con
      `def.cell(memberCtx)`. Probado con mutación (ver abajo).
- [x] T5 — `colSpan={visibleColumns.length}` en ambos estados vacío/
      cargando; `TABLE_COLUMN_COUNT` eliminada. Probado con mutación.
- [x] T6 — `ColumnPicker.jsx` + `.module.css`; Producto y Total Gauss llevan
      `enableHiding: false` en `COLUMNS` y no aparecen en el picker.
      Probado con mutación.
- [x] T7 — `ventasMlTableHelpers.js` (`loadColumnVisibility`/
      `saveColumnVisibility`), mismo patrón fail-safe que
      `tiendaNubeReconcileTableHelpers.js`. Probado con mutación.
- [x] T8 — El header pegajoso no se tocó (`table thead th` sigue con
      `position: sticky`/`top`/z-index local intactos en el CSS module).
- [x] T9 — Tests agregados en `VentasML.test.jsx` (describe "Configurable
      columns") + `ColumnPicker.test.jsx` nuevo. Ver evidencia abajo.

## Criterio de aceptación

En 1366 con la sidebar abierta se lee el título del producto sin que se
solape con Orden. El usuario esconde una columna y el header, la fila del
grupo y la fila hija coinciden.

## Checks

- `pnpm --dir frontend exec vitest run` (pnpm, NUNCA npm; `--dir X vitest`
  sin `exec` falla en este entorno)
- `pnpm --dir frontend build`

## Estado

Creado 2026-09-29. Implementado 2026-09-29.

Nuevos archivos: `frontend/src/components/ventasMl/ventasMlColumns.jsx`,
`ColumnPicker.jsx`, `ColumnPicker.module.css`, `ColumnPicker.test.jsx`,
`frontend/src/pages/ventasMlTableHelpers.js`,
`frontend/src/utils/ventasMlFormat.js` (extracción necesaria de labels/
formatters para que `ventasMlColumns.jsx` no importara de vuelta
`VentasML.jsx` — evita el ciclo). Modificados: `VentasML.jsx`,
`VentasML.module.css`, `VentasML.test.jsx`.

Evidencia de verificación (2026-09-29):

- `pnpm --dir frontend exec vitest run src/pages/VentasML.test.jsx src/components/ventasMl/`
  → 12 archivos, 189 tests, todos OK.
- `pnpm --dir frontend exec vitest run` (suite completa) → 133 archivos,
  1781 tests OK + 2 "expected fail" (mismo número que antes de este
  cambio).
- `pnpm --dir frontend build` → OK (`✓ built in 45.59s`).

TDD: T4/T5/T6/T7 se probaron en rojo con una mutación deliberada antes de
confirmarlas en verde (ver el reporte final de la conversación para el
mensaje de fallo exacto de cada una).
