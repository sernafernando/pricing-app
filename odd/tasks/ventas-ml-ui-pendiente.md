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
- [x] T2 — Paginador numerado + filas por página (frontend).
- [x] T3 — Cupón en Importe + toggle "A revisar" (frontend).
- [x] T4 — Panel: Comprador / Pago / Envío + Ver en ML + copiar ID (BE+FE).
- [x] T5 — Filtro "Solo con alertas" con conteo (BE+FE).
- [x] T6 — Exportar CSV del conjunto filtrado (BE+FE).
- [x] T7 — Resincronizar venta + permiso + "sincronizado hace X" (BE+FE).
- [x] T8 — Toggle "Canceladas" en Incluir (BE+FE; pedido del usuario 2026-09-30).

## Entrega

Pronóstico > 400 líneas: una PR por grupo, en orden.
- PR-1: T1–T3 (solo frontend).
- PR-2: T4.
- PR-3: T5–T6.
- PR-4: T7.
- T8 (BE+FE) viaja con PR-3 (T5–T6): comparte `filters.py`/`ventasMlParams.js`.

## Checks

- vitest (comparar cantidad de archivos y tests antes/después)
- `pnpm --dir frontend build` y `pnpm --dir frontend exec eslint src` (0 errores)
- `ruff format app/ tests/ && ruff check app/ tests/`
- pytest backend completo, solo

## Estado

Todas las tareas (T1–T8) hechas en la rama; sin push ni PR. Resultado final
abajo en "Cierre". Creado 2026-09-30. Línea base vitest: 133 archivos, 1794 passed + 2 expected fail.

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

### T2
- RED: `pageWindow`/`loadPageSize` no existían (8 fallan en
  `ventasMlTableHelpers.test.js`), `Pagination.jsx` no existía (suite no carga),
  y `rows per page` en `VentasML.columnSizing.test.jsx` (no hay "Página N").
- Decisión: tamaños 25/50/100/200 (el endpoint topea `limit` en 200), default
  50, persistido en `ventasml:pagesize`; cambiar el tamaño vuelve a la página 1.
  Se conserva el texto "mostrando X-Y de N ventas" y los botones
  Anterior/Siguiente (tests existentes siguen verdes sin tocarse).
- GREEN: `pnpm exec vitest run src/pages src/components/ventasMl` 577 passed.

### T3
- RED: `ventasMlColumns.test.jsx` (4 fallan: sin sub-línea de cupón) y los 3
  tests de `IncludeToggles.test.jsx` renombrados a "A revisar" (fallan con la
  etiqueta vieja).
- Decisión: el listado trae `coupon_amount` por orden, no por grupo; el grupo
  suma el de sus órdenes (`couponAmountOf`), sin sub-línea si es 0/null.
  Formato con 2 decimales como el resto de la columna. Dos tests existentes de
  `VentasML.test.jsx` se ajustaron (el badge "A revisar" ahora también es la
  etiqueta del toggle: se acotó la consulta a la tabla).
- GREEN: vitest completo 137 archivos, 1827 passed + 2 expected fail (base
  133 / 1794). eslint 0 errores / 8 warnings. build OK.

### T8 (se hizo después de T3; backend + frontend)
- Pedido: "en 'incluir' falta un toggle para sacar las canceladas" — "Pagada"
  en el filtro de operación no equivale a "todas menos canceladas" (deja
  afuera entregadas, en disputa...).
- Decisión: `include_cancelled` (default ON en ambos endpoints, no cambia los
  números actuales) oculta los GRUPOS cuyo estado de operación colapsado es
  `cancelled`. NO oculta `cancelled_ml_covered` (la plata llegó; el spec dice
  que nunca se muestre como cancelada común) ni un pack mixto (una cancelada
  + una paga = `mixed`, lo gobierna el toggle Mixta). Elegir explícitamente
  operación=Cancelada pisa el toggle (K2, igual que A revisar/En disputa).
  Va por `SalesFilter`/`build_scope`/`_apply_switches`: tabla, facets y KPI
  coinciden; `excluded_by_toggle.canceladas` y `effective_switches` lo
  reflejan. Estado en memoria como los otros toggles (los demás no se
  persisten ni van a la URL hoy; se mantuvo la misma convención).
- RED: `TestIncludeCancelled` (8 fallan: `unexpected keyword argument
  'include_cancelled'`); frontend 6 fallan (param, toggle, página). Los tests
  de integración de router se escribieron con la implementación ya hecha (RED
  observado a nivel de scope, no de endpoint).
- GREEN: pytest `test_filters_switches.py`+kpis+sales router+ml_sales_query:
  230 passed. Dos tests existentes que comparan `effective_switches` exacto se
  actualizaron con `include_cancelled`. ruff format/check OK. vitest 137
  archivos, 1832 passed + 2 expected fail; eslint 0 errores / 8 warnings.

### T4
- RED: backend `TestOrderDetailPanelFields` (3 fallan: `KeyError:
  'payment_date_approved'` / `'estimated_delivery'`); frontend
  `ventasMlFormat.test.js` (8, helpers inexistentes) y
  `SaleDetailPanel.context.test.jsx` (6 fallan: sin secciones/enlace/copiar).
- Backend (`GET /orders/{id}`, solo campos aditivos, sin llamadas nuevas a ML):
  `order.payment_date_approved` (MAX date_approved de pagos relevantes, igual
  que la regla del día), `order.coupon_amount` (suma de pagos relevantes),
  `shipment.modo_logistico`, `city`, `province`, `estimated_delivery`.
- Decisiones: "Ver en ML" = `https://www.mercadolibre.com.ar/ventas/{pack_id
  ?? order_id}/detalle` (armado con datos que ya tenemos; el link se oculta
  si no hay id). Fecha estimada: se lee de
  `raw_shipment.shipping_option.estimated_delivery_final.date` (forma
  documentada de ML; NO hay fixture capturado de un envío en el repo, así que
  el test usa esa forma modelada y el dato es null si la clave no está —
  verificar contra un envío real en producción). Tracking: se muestra y se
  copia. CUIT/marca de tarjeta/factura quedan fuera (alcance). Las secciones
  usan `<dl>`, no `<li>`, para no romper tests existentes de la lista de
  líneas.
- GREEN: pytest router/pr10/pack_scope 67 passed; vitest 139 archivos, 1847
  passed + 2 expected fail; eslint 0 errores / 8 warnings; build OK; ruff OK.

### T5
- Hallazgo: `_alert_level` se calcula en Python por orden, pero depende solo de
  datos SQL-expresibles (estado de métricas = fila dirty / fila stored /
  `gauss_status`, `neto`, `iva_reconcilia`, ejes operación/mercadería). Se
  implementó el equivalente en SQL (`_group_alert_subquery`: un grupo tiene
  alerta si ALGUNA orden no está limpia) y se aplica como filtro de scope
  (como los facets de producto) ANTES de paginar; lista, facets y KPI lo
  comparten. Sin limitación: no se filtra en Python.
- Contador: `facets.alerts_total` = grupos con alerta dentro del scope de los
  demás filtros (ignora al propio `only_alerts`, como todo facet).
- RED: `test_filters_alerts.py` (no cargaba: `alert_groups_count` inexistente),
  router `test_ml_ventas_ops_alerts_router.py` (filtro ignorado + `KeyError:
  'alerts_total'`), frontend `AlertsFilterChip`, params y página.
- Prueba de paridad: el filtro SQL devuelve EXACTAMENTE los grupos que la API
  muestra con `alert_level != ok` en alguna orden (bolsa mixta de 13 ventas:
  provisional, unresolved, neto null, iva no reconcilia, pending,
  recalculating, mercadería desconocida, packs).
- GREEN: pytest 249 passed (alerts+sales+kpis+ml_sales_query); ruff OK;
  vitest 140 archivos, 1852 passed + 2 expected fail; eslint 0 errores.

### T6
- `GET /ml-ventas-ops/sales/export` (permiso `ml_ops.ver`, mismos params que el
  listado sin paginado/orden). Decisión de diseño: recorre el MISMO
  `listar_ventas` página por página (200 grupos), así el archivo tiene lo que
  tiene la tabla, sin una segunda consulta que pueda divergir de
  `build_scope`. La primera página se pide ANTES de empezar la respuesta (un
  parámetro inválido, la feature apagada o un set enorme fallan como error
  HTTP normal, no como archivo truncado). Tope 10.000 grupos (422 con "Acotá
  los filtros"); cada página re-corre el listado, un export sin tope sería un
  request lento y ciego.
- Columnas: set fijo, una fila por ORDEN (el pack aporta una fila por miembro,
  columna `pack` los une): fecha, orden, pack, comprador, operación,
  mercadería, modo logístico, ciudad, provincia, moneda, importe, cupón ML,
  neto, total gauss, markup %, provisorio, estado de métricas, alerta. Fijo y
  no "columnas visibles" porque varias celdas visibles son compuestas
  (producto+categoría, importe+cupón). CSV con ;, punto decimal, BOM UTF-8;
  texto libre de ML con `= + - @` se neutraliza (inyección de fórmulas).
  Limitación: Excel con configuración regional es-AR espera `;` — en Sheets o
  importando con coma abre bien.
- Frontend: botón "Exportar CSV" (acciones del encabezado) usa el mismo
  `buildVentasMLFilterParams`; si falla muestra el mensaje del backend (el
  cuerpo del error llega como Blob y se lee).
- RED: `test_ml_ventas_ops_export_router.py` (7 fallaron: ruta inexistente);
  `ventasMlExport.test.js` (módulo inexistente) y el test de página (sin botón).
- GREEN: pytest export 7 passed; ruff OK; vitest 141 archivos, 1858 passed + 2
  expected fail; eslint 0 errores; build OK.

### T7
- Backend:
  - `POST /ml-ventas-ops/orders/{id}/resync` con permiso NUEVO
    `ml_ops.resincronizar` (migración `20260930_ml_ops_resincronizar`, ADMIN
    solamente, mismo molde que `ml_ops.varios_editar`; un solo head). Gasta
    pedidos a ML y reescribe campos de plata, por eso no cuelga de `ml_ops.ver`.
  - `resync_service.resync_order`: no usa `process_batch` (sus compuertas del
    sweep saltean una orden cuyo `ml_last_updated` no se movió); compone los
    mismos bloques (`_fetch_shipments`, `_fetch_payments`, `upsert_order`,
    `sync_payments_for_order`, `upsert_shipment`). TODO el HTTP va antes de la
    primera escritura: si falla traer la orden, un pago, el envío, o un pago no
    se puede mapear, no se escribe nada y el error nombra qué falló (R24,
    escenario 3). Luego encola las métricas EXPLÍCITAMENTE en la misma
    transacción (`enqueue_order_metrics`, R23: aunque los datos sean idénticos,
    los triggers ignoran el no-op); el worker recalcula la orden y su grupo.
  - Repetición (escenario 4): una resync por orden a la vez + cooldown de 10 s
    tras una exitosa (409); una fallida no arranca cooldown. En proceso a
    propósito: las escrituras son upserts idempotentes protegidos por
    `ml_last_updated`, el guard evita gastar pedidos a ML por un doble click.
  - `GET /ml-ventas-ops/sales/sync-status`: MAX(`last_success_at`) de los
    cursores `sweep` y `ml_activity` (un pase cortado por presupuesto no sella
    `last_success_at`, así que no promete frescura que no alcanzó; el
    `backfill` no cuenta). Sin cron ni polling nuevo.
  - Hallazgo: `get_payment` (proxy ml-webhook) devuelve `payment_id`, no `id`
    — un fixture mío lo tenía mal y el test lo delató.
- Frontend: footer del panel con "Sincronizado hace X" (`timeAgo`, calculado al
  render, sin timers) y botón "Resincronizar" (solo con permiso; deshabilitado
  mientras corre; error del backend visible y sin recargar datos; éxito recarga
  el detalle y avisa a la página para refrescar lista/KPI/estado de sync). La
  página muestra "sincronizado hace X" junto a "actualizado".
- RED: `test_resync_service.py` (no cargaba: módulo inexistente),
  `test_ml_ventas_ops_resync_router.py` + `test_migration_ml_ops_resincronizar.py`
  (11 fallaron), frontend `timeAgo` (4), `SaleDetailPanel.resync.test.jsx`
  (6 de 9) y 2 de página.
- GREEN: resync 14 + router/migración 11 passed; postgres real: el helper
  `enqueue_order_metrics` pasa por la función PL/pgSQL
  (`TestEnqueueOrderMetricsHelper`, 1 passed, no skipped).

## Cierre

- vitest: base 133 archivos / 1794 passed (+2 expected fail) → final 142
  archivos / 1873 passed (+2 expected fail). eslint src: 0 errores, 8 warnings
  (los preexistentes). `pnpm build` OK.
- Backend: ruff format --check y ruff check limpios; `alembic heads` = 1
  (`20260930_ml_ops_resincronizar`). Suite completa SOLA
  (`pytest tests/ -q -p no:randomly`): 7581 passed, 16 skipped, 0 failed, 12m40s.
  La primera corrida completa cortó en un test de presupuesto de queries
  (`test_five_rows_stay_within_a_fixed_query_budget`): el contador de alertas
  (T5) suma UNA lectura de `ml_order_metrics` por request; el techo pasó de 2 a
  3 con comentario (sigue siendo O(1), no por fila).
- Pendiente / límites honestos: (1) `estimated_delivery` sale de la forma
  documentada de ML (`raw_shipment.shipping_option.estimated_delivery_final`),
  sin fixture capturado en el repo: verificar contra un envío real. (2) CSV con
  coma: Excel es-AR espera `;`. (3) Guard de resync es por proceso. (4) El
  permiso nuevo hay que asignarlo a quien no sea ADMIN por overrides. (5) No se
  pushó ni se abrió PR (pedido explícito).

### Fix T6 (export CSV): producto, día de acreditación, formato Excel es-AR
- Defectos pedidos por el coordinador: (1) faltaba el producto; (2) la fecha
  era `date_created` y la regla (#1368) es el día de acreditación; (3) el
  formato no abría bien en Excel es-AR.
- Cambios: columnas `producto`, `sku`, `cantidad` (varios ítems de una orden
  se unen con " | ", nunca se elige uno; mismo orden en las tres);
  `fecha_acreditacion` (MAX de `date_approved` de pagos relevantes de los
  miembros del grupo, vía `member_accreditation_dates`, sin regla nueva; un
  pack repite el día de su último miembro) y `fecha_creacion`; delimitador `;`
  y coma decimal en la plata, BOM se mantiene. El guard de inyección de
  fórmulas cubre título y SKU. Supera la limitación (2) del cierre: el CSV ya
  abre bien en Excel es-AR.
- RED: 8 de 10 tests del archivo `test_ml_ventas_ops_export_router.py` fallaron
  (columnas inexistentes / formato viejo). GREEN: export + sales router 106
  passed; ruff limpio. Frontend sin cambios (sus tests no asertan el formato).

### Fix observaciones (review de la UI de Ventas ML)
Rama `fix/ventas-ml-ui-observaciones`, TDD estricto (RED observado antes de cada fix).
- Ruta: delegated direct, un solo writer.
1. Export caro: cada página re-corría `listar_ventas` completo (facets + contador de
   alertas). Ahora `listar_ventas` y el export comparten UN camino, `_sales_page`;
   el export pasa `with_facets=False`. RED: `alert_groups_count` se llamaba en el
   export (`assert [1] == []`; los controles del listado sí pasaban). GREEN: el export
   no corre facets (`as bucket`) ni el contador.
2. Conexión retenida esperando a ML. (a) resync: `resync_order` hace `db.commit()`
   tras el chequeo de existencia, antes de todo HTTP; la transacción de escritura
   arranca después del último HTTP (semántica all-HTTP-before-first-write intacta).
   RED: `db.in_transaction()` era True en las 3 llamadas (order/shipment/payment).
   (b) export: cada página corre en su propio `get_background_db()` (pedida y cerrada
   por página); la sesión del request se libera con `db.rollback()` tras la primera
   página, que sigue validándose antes de arrancar la respuesta (422 intacto).
   RED: `assert 0 == 3` sesiones cortas abiertas.
3. `_finished_at` crecía sin límite: `_prune_expired` en `_try_begin` y `_end`.
   RED: la entrada vencida seguía en el dict.
4. `_receiver_address_field` -> `_nested_str_field` (lee claves anidadas de cualquier
   JSON crudo, también `raw_shipment`). RED: ImportError del nombre nuevo.
