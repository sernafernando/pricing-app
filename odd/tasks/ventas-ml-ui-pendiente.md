# Ventas ML — UI pendiente del rediseño

## Objetivo

Cerrar todo lo que el diseño Stitch (`docs/design/ventas-ml/`) y el rediseño
(`openspec/changes/ventas-ml-rediseno/`) piden para la pantalla Ventas ML y
hoy no existe. Pedido del usuario (2026-09-30): "hacelo y todo lo demás de la
UI que falta".

## Alcance

Incluido (inventario verificado contra main @ 4d10c3af):

- Anchos de columna ajustables por el usuario (persistidos por usuario,
  botón para restablecer, mínimo por columna). Reusar el mecanismo existente
  (`components/ml-bot/useColumnSizing.js`, `ResizableTableShell.jsx`,
  `components/tn-reconcile/ReconcileTable.jsx`), no inventar otro.
- Paginador numerado + selector de filas por página (backend ya acepta
  `limit`/`offset`).
- Columna Importe: sub-línea "cupón ML $X" cuando `coupon_amount > 0`.
- Panel de detalle: secciones Comprador, Pago, Envío; botón "Ver en ML" y
  copiar ID en el encabezado. Exponer lo que falte en el backend (fecha de
  aprobación del pago; tracking/fecha estimada si ya se persiste).
- Filtro "Solo con alertas" con conteo (backend: filtro + facet).
- Exportar CSV del conjunto filtrado (mismo scope que el listado).
- Resincronizar una venta desde el panel (re-trae de ML y recalcula Costo
  Gauss) con permiso propio; indicador "sincronizado hace X" con el último
  sync real.
- Toggle "Sin clasificar" → "A revisar" (nombre del spec R9).

Fuera de alcance (decidido en el diseño/propuesta): tendencias/objetivos de
las tarjetas (datos inventados por Stitch), miniaturas reales, CUIT, factura,
marca/dígitos de tarjeta, selector de cuenta, filtro de tienda oficial, vista
por marcas con colores (trabajo aparte).

## Restricciones

- Las mismas reglas de plata de siempre: `RELEVANT_PAYMENT_STATUSES` por pago;
  día = MAX(date_approved). El CSV y el filtro de alertas usan el MISMO scope
  que el listado (`ml_sales_query`), nunca una consulta paralela.
- Frontend: pnpm; CSS Modules; columnas definidas en `ventasMlColumns.jsx`.
- Sin cron. Sin atribución de IA en commits/PRs.

## TDD

Strict TDD: enabled (config de sesión). Runners:
- `pnpm --dir frontend exec vitest run`
- `cd backend && venv/bin/python -m pytest tests/ -q -p no:randomly` (SOLA)

## Tareas

Ruta: delegated direct (writer único, 2+ archivos no triviales por tarea).

- [x] T1 — Anchos ajustables + restablecer (frontend).
- [ ] T2 — Paginador numerado + filas por página (frontend).
- [ ] T3 — Cupón en Importe + toggle "A revisar" (frontend).
- [ ] T4 — Panel: Comprador / Pago / Envío + Ver en ML + copiar ID (BE+FE).
- [ ] T5 — Filtro "Solo con alertas" con conteo (BE+FE).
- [ ] T6 — Exportar CSV del conjunto filtrado (BE+FE).
- [ ] T7 — Resincronizar venta + permiso + "sincronizado hace X" (BE+FE).

## Entrega

Pronóstico > 400 líneas: una PR por grupo, en orden.
- PR-1: T1–T3 (solo frontend).
- PR-2: T4.
- PR-3: T5–T6.
- PR-4: T7.

## Checks

- vitest (comparar cantidad de archivos y tests antes/después)
- `pnpm --dir frontend build` y `pnpm --dir frontend exec eslint src` (0 errores)
- `ruff format app/ tests/ && ruff check app/ tests/`
- pytest backend completo, solo

## Estado

Creado 2026-09-30. Línea base vitest: 133 archivos, 1794 passed + 2 expected fail.

## Evidencia

### T1 (ruta: delegated direct, writer único)
- RED: `ventasMlTableHelpers.test.js` (7 fallan: `resizeColumns` no existe) y
  `VentasML.columnSizing.test.jsx` (6 fallan: `Unable to find role="separator"`).
- Decisión: el drag de TanStack mueve el borde a otra escala porque las `size`
  se renderizan como proporción; se miden los px reales al empezar el drag y se
  mueve el borde entre columna y vecina derecha (total constante, mínimo por
  columna en `minSize`). Reusa `useColumnSizing` (estado, guardado, reset) con
  clave `ventasml:colsizing`. Sin grip en `alerta` ni en la última visible.
  Teclado: flechas ±10px sobre el grip.
- GREEN: 13/13 tests nuevos. vitest completo: 135 archivos, 1807 passed + 2
  expected fail (antes 133 / 1794). eslint: 0 errores, 8 warnings. build OK.
