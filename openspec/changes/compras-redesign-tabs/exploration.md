# Exploration: compras-redesign-tabs

Aplicar el lenguaje visual "Editorial Finance Terminal" del `TabCCProveedores` rediseñado (PRs #618 + #619 mergeados) a los 7 tabs/paneles restantes del módulo compras + sus modales asociados.

## Current State

El módulo compras tiene 8 componentes principales en `frontend/src/components/compras/` y 11 modales asociados. Comparten una **estructura subyacente uniforme** (todos usan `<table className={styles.table}>` + `emptyState` + filtros en topBar) pero **divergen en estética visual** porque cada uno mantiene su propio CSS module heredado de iteraciones previas.

`TabCCProveedores` (1190 líneas) ya fue rediseñado con la dirección visual de referencia:
- Hero card con monogram + 3 metric tiles
- Quick actions como chips
- Tabla unificada con `<colgroup>`, alignment correcto, tabular-nums + font-mono
- Cards colapsables con `<details>/<summary>` + estado badges
- Empty/loading states con personalidad
- Mantiene tokens `--cf-*`

Los tabs sin rediseñar usan el patrón CSS antiguo (sin colgroup, sin tabular-nums, badges sin variantes de estado, empty states genéricos, botones primarios saturados con bg de color sólido).

## Affected Areas

### Tabs (7)
- `TabPedidosCompra.jsx` (737) + .module.css (369) — **alta complejidad/uso** · tabla + 6 filtros + creación + acciones por fila (ver, editar, pagar, eliminar) + paginación
- `TabOrdenesPago.jsx` (828) — **alta complejidad/uso** · tabla + filtros + acciones (anular, cancelar pendiente, ejecutar pago)
- `TabNCsLocales.jsx` (634) — **media** · tabla + workflow estado (borrador → pendiente → aprobado → aplicada) + aplicar
- `TabSaleDocumentCatalog.jsx` (194) — **baja** · admin: tabla simple + filtros + sección "faltantes"
- `TabPapelera.jsx` (288) — **baja** · admin: tabla simple + restaurar
- `TabReconciliacion.jsx` (320) — **baja-media** · tabla + métricas (4 cards) + forzar
- `PanelImputaciones.jsx` (366) — **media** · panel reusable: tabla + acciones desimputar/reimputar

### Modales (11)
**Detalle (lectura):**
- `ModalPedidoDetalle.jsx` (543) — alto uso
- `ModalOrdenPagoDetalle.jsx` (416) — alto uso
- `ModalNCLocalDetalle.jsx` (726) — medio uso

**Creación (formulario):**
- `ModalPedidoCompra.jsx` (319)
- `ModalOrdenPagoNueva.jsx` (716)
- `ModalNCLocal.jsx` (318)

**Operación (acción puntual):**
- `ModalEjecutarPago.jsx` (375)
- `ModalAplicarNC.jsx` (399)
- `ModalCorregirPedido.jsx` (328)
- `ModalVincularFactura.jsx` (305)
- `ModalVincularFacturaNC.jsx` (309)
- `ModalConfirmarEliminacion.jsx` (178)

**Total**: ~9.500 líneas de JSX a tocar.

## Patterns Found

Componentes/conceptos a abstraer (todos derivables del CC ya hecho):

| Patrón | Estado actual | Propuesta |
|---|---|---|
| Tabla con colgroup + tabular-nums + alignment | `<LedgerTable />` interno en CC | Extraer a `<DataTable />` shared |
| Empty state con ícono + título + sub-mensaje | `heroEmpty / emptyRow / emptyBlock` en CC | Extraer a `<EmptyState />` |
| Badge de estado (Pagado/Parcial/Pendiente/Cancelado/Borrador) | `<EstadoPedidoBadge />` interno en CC | Extraer a `<EstadoBadge />` con variantes (pedido, op, nc) |
| Metric tile (label + value + hint + tone) | `<MetricTile />` interno en CC | Extraer a shared (TabReconciliacion lo necesita) |
| Loading state centrado | `heroLoading` en CC | Extraer a `<LoadingBlock />` |
| Filters toolbar (estado, empresa, proveedor, fechas, búsqueda) | Repetido inline en cada tab | Extraer a `<FiltersBar />` con slots |
| Quick action chips | `actionChip / actionChipAccent / actionChipDanger` en CC | Reusar clases CSS |
| Card colapsable con summary completo | `<GrupoPedidoCard />` interno en CC | Patrón aplicable a OP detalle, NC detalle |

## Approaches

### 1. **Change único (`compras-redesign-tabs`)** — todo en un PR grande
- Pros: una sola review, terminás de una, no hay que coordinar entre fases
- Cons: PR de ~3.000-4.000 líneas, alto riesgo de regresión, difícil de mergear si algún tab no convence visualmente
- Effort: **High** (3-5 días)

### 2. **4 changes sub-secuenciales** — fragmentado por dominio
- `compras-redesign-pedidos` — TabPedidosCompra + sus modales (Detalle, Compra, Corregir)
- `compras-redesign-ops` — TabOrdenesPago + sus modales (Detalle, Nueva, EjecutarPago)
- `compras-redesign-ncs` — TabNCsLocales + sus modales (Detalle, Nueva, AplicarNC, VincularFacturaNC)
- `compras-redesign-admin` — TabReconciliacion + TabSaleDocumentCatalog + TabPapelera + PanelImputaciones + ModalConfirmarEliminacion
- Pros: cada PR revisable independiente, rollback fácil, feedback iterativo entre changes
- Cons: 4 ciclos de review/merge en lugar de 1, riesgo de inconsistencia si los criterios derivan entre changes
- Effort: **High** (suma similar al opt 1, distribuida)

### 3. **Sub-change de "shared components" + 4 changes de tabs** — extracción primero
- `compras-redesign-shared` (primero): extraer DataTable, EstadoBadge, EmptyState, MetricTile, FiltersBar al directorio shared. Refactorizar TabCCProveedores para usarlos (cero cambio visual).
- Después: 4 changes consumen los shared
- Pros: máxima reutilización, bug fix en 1 lugar afecta a todos, código más limpio en el largo plazo
- Cons: 5 PRs en total, primer PR es "invisible" (refactor sin cambio visual), retrasa el deliverable visual del user
- Effort: **Highest** (suma del opt 2 + extracción)

## Recommendation

**Opción 2 (4 changes sub-secuenciales)** sin extracción shared formal todavía.

**Por qué:**
- El user ya validó la estética con CC (PRs #618 + #619 mergeados sin pedir cambios visuales mayores). Lo que sigue es replicar, no diseñar.
- Extraer componentes shared (opt 3) **antes** de validar el patrón en otros contextos (lista plana, workflows distintos) es prematuro — mejor copiar 4 veces y abstraer al final cuando el patrón esté probado.
- Fragmentar en 4 reduce blast radius: si TabOrdenesPago no convence visualmente, lo iteramos sin bloquear los otros 3 tabs.
- El usuario ya mergea cada PR rápido — el ciclo de review/merge no es bottleneck.

**Orden propuesto** (por uso real, no por complejidad):
1. `compras-redesign-pedidos` — más usado, más feedback útil
2. `compras-redesign-ops` — patrón similar a pedidos, replica fácil
3. `compras-redesign-ncs` — workflow distinto, valida flexibilidad del patrón
4. `compras-redesign-admin` — bajo tráfico, menos riesgo, último

**Modales**: cada change incluye los modales de su dominio. Deja `ModalConfirmarEliminacion` (genérico) en el último change por ser shared.

**Imputaciones**: `PanelImputaciones` ya está integrado inline en CC (PR #618). Como standalone solo se usa en debug/admin → última prioridad. Va en `compras-redesign-admin`.

## Risks

1. **Densidad de información**: TabPedidosCompra y TabOrdenesPago tienen muchos campos por fila (estado, fecha, número, proveedor, monto, factura, acciones). Aplicar el mismo padding/font-size del CC podría hacer que las filas no entren a 1280px. **Mitigación**: ajustar columnas con colgroup específico por tab, no copiar widths del CC.

2. **Workflow visual de NCs locales**: las NCs tienen estados (`borrador → pendiente_aprobacion → aprobado → aplicada_parcial → aplicada`) más granulares que pedidos. El `<EstadoPedidoBadge />` actual mapea 5 tonos pero NC necesita variantes propias. **Mitigación**: crear `<EstadoNCBadge />` o pasar `variant="nc"` al shared.

3. **Modales de detalle muy grandes** (ModalNCLocalDetalle 726, ModalPedidoDetalle 543): rediseñar implica tocar mucho JSX. Riesgo de romper feature de Timeline / payload colapsable / acciones específicas. **Mitigación**: tests visuales manuales por cada modal antes de mergear.

4. **PanelImputaciones standalone vs inline**: hoy se usa inline (CC) y como tab/panel separado. Coherencia visual entre los dos contextos. **Mitigación**: tratar como un solo componente, propagar cambios a ambos usos.

5. **Tokens nuevos pendientes**: la propuesta del CC mencionó `--cf-shadow-card`, `--cf-saldo-positive/negative`, `--font-mono` formal. **No se agregaron**. Si avanzamos sin definirlos, vamos a tener `var(--font-mono, ui-monospace, ...)` repetido 30+ veces. **Mitigación**: agregar los 3 tokens en un commit chico antes del primer change (prerequisito).

## Open Questions

1. **¿Modales se rediseñan junto con su tab principal o aparte?** Recomiendo **junto** para que tab + modal sigan coherentes en cada PR.
2. **¿Extraemos componentes shared ahora o después?** Recomiendo **después** (post 4 changes), una vez probado el patrón en distintos contextos.
3. **¿Algún tab tiene prioridad por dolor real?** Si el user tiene un dolor concreto (ej. "Pedidos se rompe en mobile"), arrancar por ahí en lugar del orden por uso.
4. **¿Tokens nuevos los aprueba el user antes del primer change o los agregamos juntos?** Recomiendo **commit prerequisito** con los 3 tokens (`--cf-shadow-card`, `--font-mono`, `--cf-saldo-positive/negative`) antes de propose.

## Ready for Proposal

**Sí**, con las 4 open questions cerradas por el user. El alcance está claro, los riesgos identificados, el orden recomendado tiene justificación.

**Sugerencia al orquestador**:
- Confirmar opt 2 (4 changes) y orden propuesto (pedidos → ops → ncs → admin) con el user
- Cerrar las 4 open questions
- Si OK → proceder con `/sdd-propose compras-redesign-pedidos` como primer change (el `compras-redesign-tabs` actual queda como "umbrella" o se descarta a favor de los 4 sub-changes)
