# Ventas ML — tira de KPIs y toggles (frontend)

## Objetivo

Que al filtrar (una marca, una fecha, lo que sea) la pantalla muestre **el total
de lo filtrado**, arriba de la tabla, con la forma del diseño de Stitch
"Ventas ML - Dashboard de Operaciones".

## Problema

El backend de esto está terminado y no se ve. `GET /ml-ventas-ops/sales/kpis`
acepta EXACTAMENTE los mismos filtros que la lista y devuelve los totales del
conjunto filtrado. El frontend nunca lo llama. Además, de los filtros que el
backend soporta, el frontend no manda los cuatro toggles
(`include_unknown`, `include_in_dispute`, `include_mixed`, `include_provisional`).

Consecuencia: la promesa "lo que veo es lo que suma" es cierta del lado del
servidor y no existe del lado del usuario.

## Por qué ahora

Hay presión para mostrar resultado. Esto es frontend puro contra un endpoint
terminado y testeado: la parte cara ya está hecha.

## Alcance autorizado

- `frontend/src/pages/VentasML.jsx` — llamar al endpoint, pasar los mismos
  params que ya construye para la lista, sumar los cuatro toggles.
- Componentes nuevos bajo `frontend/src/components/ventasMl/`.
- NADA de backend. NADA de la vista por marcas con colores (eso es otro trabajo).

## Contrato del endpoint (ya existe, no tocar)

`GET /ml-ventas-ops/sales/kpis` — mismos params que la lista salvo
`sort`/`limit`/`offset`:
`operation_status_filter, goods_status_filter, sold_month, date_from, date_to,
q, marcas, subcategorias, pms, include_unknown, include_in_dispute,
include_mixed, include_provisional`

Devuelve `SalesKpiResponse`:
`groups_count, orders_count, gross_billed_ars, gross_billed_other{},
neto_sum, neto_unknown_count, total_gauss_sum, total_gauss_ok_count,
total_gauss_provisional_count, total_gauss_unresolved_count,
markup_weighted_pct (nullable), recalculating_count, pending_count,
failed_count, markup_skipped_count, worker_alive,
excluded_by_toggle{a_revisar,en_disputa,mixta,provisorio},
effective_switches{}`

## Tareas

- [x] T1 — `KpiStrip.jsx` + `.module.css`: seis tarjetas como el Stitch
      (Ventas, Facturado bruto, Neto ML, Total Gauss, Markup promedio,
      Desglose incompleto). Tokens del design system, nada de Tailwind.
- [x] T2 — Honestidad de los números: lo que no se pudo resolver se CUENTA
      aparte, nunca se suma como cero. `markup_weighted_pct` nulo se muestra
      como "—", no como 0%. La tarjeta de "Desglose incompleto" junta
      `neto_unknown_count` + `total_gauss_unresolved_count` +
      `recalculating_count` + `pending_count` + `failed_count` y dice de qué
      está hecha.
- [x] T3 — Moneda: `gross_billed_ars` es ARS. `gross_billed_other` son otras
      monedas y NO se suman a los pesos; se muestran aparte.
- [x] T4 — Los cuatro toggles en la UI (`IncludeToggles.jsx`), con el badge
      de cuántos grupos esconde cada uno apagado (`excluded_by_toggle`),
      visible solo mientras el toggle está apagado.
- [x] T5 — Cablear: los toggles van a la lista Y al KPI, siempre juntos, vía
      un único builder compartido (`utils/ventasMlParams.js`,
      `buildVentasMLFilterParams`) que consumen `cargarVentas` y `cargarKpis`.
- [x] T6 — Estados: cargando ("Cargando métricas…"), error ("No se pudieron
      cargar las métricas."), y `worker_alive: false` avisado con banner.
- [x] T7 — Tests con Vitest (`css: false`): paridad de params entre lista y
      KPI (incluye el toggle apagándose en ambos requests a la vez), el
      markup nulo, el conteo de incompletos, y que las otras monedas no se
      sumen a ARS.

### Evidencia de verificación (2026-09-29)

- `pnpm --dir frontend exec vitest run src/pages/VentasML.test.jsx src/components/ventasMl/`
  → 11 test files passed, 181 tests passed.
- `pnpm --dir frontend exec vitest run` (suite completa)
  → 132 test files passed, 1773 passed | 2 expected fail (pre-existentes, no
  tocados por este feature).
- `pnpm --dir frontend build` → build OK (los warnings de chunk-size son
  preexistentes, ajenos a este feature).

Nota: el comando literal `pnpm --dir frontend vitest run` (sin `exec`) falla
en este entorno con `ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL` — es un problema del
wrapper de pnpm en esta instalación, no del código. `pnpm --dir frontend exec
vitest run ...` es equivalente y sí funciona.

### Archivos

- Nuevos: `frontend/src/components/ventasMl/KpiStrip.jsx` + `.module.css` +
  `.test.jsx`; `frontend/src/components/ventasMl/IncludeToggles.jsx` +
  `.module.css` + `.test.jsx`; `frontend/src/utils/ventasMlParams.js` +
  `.test.js`.
- Modificado: `frontend/src/pages/VentasML.jsx` (estado de los 4 toggles,
  `cargarKpis`, builder compartido para `cargarVentas`, render de
  `KpiStrip`/`IncludeToggles`) y su `VentasML.test.jsx` (4 tests nuevos de
  paridad/wiring).

## Criterio de aceptación

Filtrás una marca → las seis tarjetas muestran el total de esa marca, y el
número de "Ventas" coincide con el total de la paginación de la tabla.

## Checks

- `pnpm --dir frontend vitest run` (pnpm, NUNCA npm)
- `pnpm --dir frontend build`

## Estado

Creado 2026-09-29. Implementado y verificado el mismo día (ver Evidencia de
