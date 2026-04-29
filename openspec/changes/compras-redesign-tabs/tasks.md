# Tasks: compras-redesign-tabs

Cada task referencia archivos y acceptance criteria concretos. Para retomar una task sin contexto, leer:
- `openspec/changes/compras-redesign-tabs/design.md` (decisiones técnicas + API + mapping de estados)
- `openspec/changes/compras-redesign-tabs/specs/*.md` (requirements + scenarios)

**Convención de size**: S (≤30 LOC), M (30-150 LOC), L (150-400 LOC), XL (>400 LOC).

---

## Batch 0 — Tokens (PR0)

### T0.1 — Agregar 4 tokens nuevos en design-tokens.css
**Size**: S · **Deps**: ninguna · **Branch**: `develop`

**Files**:
- MODIFY `frontend/src/styles/design-tokens.css`

**Action**: agregar las 4 variables nuevas al `:root` y mirroreadas en `:root[data-theme="light"]` donde aplique:

```css
/* Monospace stack centralizada */
--font-mono: ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Code", Menlo, Consolas, monospace;

/* Sombras reusables */
--cf-shadow-card: 0 1px 0 rgba(255, 255, 255, 0.05) inset, 0 2px 8px -2px rgba(0, 0, 0, 0.1);
--cf-shadow-modal: 0 20px 60px -20px rgba(0, 0, 0, 0.4);

/* Alias semánticos contables */
--cf-saldo-positive: var(--cf-accent-green);
--cf-saldo-negative: var(--cf-accent-red);
```

En `:root[data-theme="light"]` ajustar `--cf-shadow-card` y `--cf-shadow-modal` a versiones más sutiles para fondo claro.

**Acceptance criteria**:
- [ ] Las 4 variables están definidas en `:root`
- [ ] `--cf-shadow-card` y `--cf-shadow-modal` tienen variante en `:root[data-theme="light"]`
- [ ] `npm run build` clean
- [ ] `npx eslint frontend/src/` clean
- [ ] Inspección manual: ningún componente fuera de compras se ve diferente (los tokens son aditivos, sin consumers todavía)

**PR title**: `feat(ui): agregar tokens --font-mono, --cf-shadow-card/modal, --cf-saldo-positive/negative`

---

## Batch 1 — Shared components + refactor CC (PR1)

> **Importante**: el refactor del CC (T1.7) DEPENDE de que los 6 componentes shared (T1.1-T1.6) estén creados primero. T1.1-T1.6 son **paralelizables entre sí**.

### T1.1 — DataTable component
**Size**: L · **Deps**: T0.1

**Files**:
- CREATE `frontend/src/components/compras/_shared/DataTable.jsx`
- CREATE `frontend/src/components/compras/_shared/DataTable.module.css`

**Action**: extraer la lógica del `<LedgerTable />` interno actual de `TabCCProveedores.jsx` (líneas ~640-740 aprox). API según design.md:
- Props: `columns`, `rows`, `renderCell`, `loading`, `empty`, `onRowClick`, `navegableRowFn`, `minWidth`
- `<colgroup>` generado dinámicamente desde `columns[].width`
- Headers con `align` desde `columns[].align`
- Slots: `loading` muestra `<LoadingBlock />`, `empty` muestra `<EmptyState tone='inline' />`
- Hover row con accent lateral `scaleY` cuando `navegable`
- `min-width: 720px` default + scroll-x

**CSS migrado desde TabCCProveedores.module.css**:
- `.tableWrapper`, `.table`, `.colFecha`, `.colOrigen`, `.colNum`, `.colMon`, `.colAccion`, `.thLeft`, `.thRight`, `.thCenter`, `.tdSecondary`, `.tdMoneda`, `.tdAccion`, `.rowClickable`, `.iconBtn`

**JSDoc**: bloque al inicio con descripción + ejemplo de uso + tipos de props.

**Acceptance criteria**:
- [ ] Archivo JSX con JSDoc completo (props documentadas, ejemplo)
- [ ] CSS Module con clases migradas del CC
- [ ] Componente renderea tabla con colgroup dinámico
- [ ] Slot `loading` y `empty` funcionan
- [ ] `onRowClick` invocado al click; `navegableRowFn` controla `cursor: pointer` y accent lateral
- [ ] ESLint clean
- [ ] No importa de `Tab*`, `Modal*`, `Panel*` (regla `import/no-cycle`)

---

### T1.2 — EstadoBadge component (con mapping de 3 variants)
**Size**: M · **Deps**: T0.1

**Files**:
- CREATE `frontend/src/components/compras/_shared/EstadoBadge.jsx`
- CREATE `frontend/src/components/compras/_shared/EstadoBadge.module.css`

**Action**: implementar mapping completo según design.md sección "EstadoBadge mapping completo".

```jsx
const MAPPING_PEDIDO = {
  pagado:               { tone: 'pagado', label: 'Pagado', icon: CheckCircle2 },
  pagado_parcial_zero:  { tone: 'pagado', label: 'Pagado', icon: CheckCircle2 }, // saldo=0
  pagado_parcial:       { tone: 'parcial', label: 'Parcial', icon: Clock },
  aprobado:             { tone: 'pendiente', label: 'Pendiente', icon: CircleAlert },
  pendiente_aprobacion: { tone: 'borrador', label: 'Sin aprobar', icon: Clock },
  borrador:             { tone: 'borrador', label: 'Borrador', icon: Clock },
  rechazado:            { tone: 'cancelado', label: 'Rechazado', icon: X },
  cancelado:            { tone: 'cancelado', label: 'Cancelado', icon: X },
};
const MAPPING_OP = { /* pagado, pendiente, anulado, cancelado */ };
const MAPPING_NC = { /* aplicada, aplicada_parcial, aprobado, pendiente_aprobacion, borrador, rechazado, cancelado */ };
```

Para `variant='pedido'` con `saldo`: si estado es `pagado_parcial` y `saldo===0` → mostrar como Pagado.

Fallback: si la combinación variant+estado no existe en el mapping → renderea badge "Desconocido" tono gris.

**CSS migrado**:
- `.estadoBadge`, `.estadoPagado`, `.estadoParcial`, `.estadoPendiente`, `.estadoCancelado`, `.estadoBorrador`
- También migran badges debe/haber/ajuste internas: `.badgeDebe`, `.badgeHaber`, `.badgeAjuste` (porque son del mismo dominio visual)

**Acceptance criteria**:
- [ ] Los 3 mappings completos según design.md
- [ ] Soporta prop `size: 'sm'|'md'`, default `'sm'`
- [ ] Saldo solo afecta variant=pedido
- [ ] Fallback "Desconocido" para combos no mapeados (no throw)
- [ ] JSDoc completo
- [ ] ESLint clean

---

### T1.3 — EmptyState component
**Size**: M · **Deps**: T0.1

**Files**:
- CREATE `frontend/src/components/compras/_shared/EmptyState.jsx`
- CREATE `frontend/src/components/compras/_shared/EmptyState.module.css`

**Action**: extraer empty states del CC (heroEmpty, emptyRow, emptyBlock) en un solo componente con prop `tone: 'default'|'inline'|'hero'`.

**Props**: `icon`, `title`, `subtitle`, `cta` (opcional `{label, onClick, variant}`), `tone`.

**CSS migrado**:
- `.heroEmpty`, `.heroEmptyIcon`, `.heroEmptyTitle`, `.heroEmptySub` → tone='hero'
- `.emptyRow`, `.emptyRowInner` → tone='inline'
- `.emptyBlock` → tone='default'

**Acceptance criteria**:
- [ ] 3 tones funcionando con diferencia visual clara (padding, border dashed, ícono size)
- [ ] CTA opcional renderea botón con `actionChip` o `btnPrimary` según variant
- [ ] JSDoc completo
- [ ] ESLint clean

---

### T1.4 — MetricTile component
**Size**: M · **Deps**: T0.1

**Files**:
- CREATE `frontend/src/components/compras/_shared/MetricTile.jsx`
- CREATE `frontend/src/components/compras/_shared/MetricTile.module.css`

**Action**: extraer del CC. 4 tones: debe (red border-left), haber (green), neutral (gray), estimate (orange + striped pattern).

**Props**: `label`, `value`, `hint`, `tone`, `icon` (opcional override).

**Default icons** por tone:
- `debe` → ArrowDownToLine
- `haber` → ArrowUpFromLine
- `neutral` → Wallet
- `estimate` → Wallet

**CSS migrado**:
- `.metricTile`, `.metricTileDebe`, `.metricTileHaber`, `.metricTileNeutral`, `.metricTileEstimate`
- `.metricLabelRow`, `.metricLabel`, `.metricValue`, `.metricHint`

**Acceptance criteria**:
- [ ] Border-left correcto por tone
- [ ] `tone='estimate'` con striped pattern via `repeating-linear-gradient`
- [ ] `value` usa `font-family: var(--font-mono)` + `tabular-nums`
- [ ] Hover: `transform: translateY(-1px)` + border-color cambia
- [ ] JSDoc completo
- [ ] ESLint clean

---

### T1.5 — LoadingBlock component
**Size**: S · **Deps**: T0.1

**Files**:
- CREATE `frontend/src/components/compras/_shared/LoadingBlock.jsx`
- CREATE `frontend/src/components/compras/_shared/LoadingBlock.module.css`

**Action**: extraer del CC. Spinner azul (`Loader2` size 28) + texto opcional.

**Props**: `text` (default "Cargando…"), `tone: 'block'|'inline'`.

**CSS migrado**: `.heroLoading`, `.heroLoadingText`, `.spin`, `.centered`.

**Acceptance criteria**:
- [ ] Spinner con animación 1s linear infinite, color `--cf-accent-blue`
- [ ] Texto debajo en `font-sm + text-secondary`
- [ ] tone `inline` con menos padding
- [ ] JSDoc completo

---

### T1.6 — FiltersBar component
**Size**: S · **Deps**: T0.1

**Files**:
- CREATE `frontend/src/components/compras/_shared/FiltersBar.jsx`
- CREATE `frontend/src/components/compras/_shared/FiltersBar.module.css`

**Action**: contenedor flexible con `flex-wrap: wrap` + `gap: var(--spacing-sm)`. Slot `actions` con `margin-left: auto`.

**Props**: `children`, `actions`.

**Acceptance criteria**:
- [ ] Children en flex-wrap
- [ ] `actions` slot al final (margin-left auto)
- [ ] En mobile (<768px) el `actions` baja a línea nueva
- [ ] JSDoc completo

---

### T1.7 — Refactor TabCCProveedores para consumir shared
**Size**: L · **Deps**: T1.1, T1.2, T1.3, T1.4, T1.5, T1.6

**Files**:
- MODIFY `frontend/src/components/compras/TabCCProveedores.jsx` (reemplazar componentes internos por imports de shared)
- MODIFY `frontend/src/components/compras/TabCCProveedores.module.css` (eliminar clases migradas a shared)

**Action**:
1. Importar los 6 shared con paths relativos
2. Reemplazar `<LedgerTable>` interno por `<DataTable>` del shared (ajustar API: `columns`/`rows`/`renderCell`)
3. Reemplazar `<EstadoPedidoBadge>` interno por `<EstadoBadge variant='pedido'>` shared
4. Reemplazar empty states inline por `<EmptyState>`
5. Reemplazar `<MetricTile>` interno por shared
6. Loading states usan `<LoadingBlock>`
7. Eliminar de `TabCCProveedores.module.css` las clases listadas en design.md "Migración de CSS classes" (mantener solo las específicas del CC: `.searchBar`, `.searchProveedor`, `.input`, `.select`, `.errorBanner`, `.hero`, `.monogram`, `.heroIdentity*`, `.heroChip`, `.metrics`, `.accionesBar`, `.actionChip*`, `.viewSwitcher`, `.viewBtn*`, `.ledgerToolbar`, `.ledgerTitle*`, `.grupoCard*`, `.grupoSummary*`, `.grupoHeader*`, `.grupoBody`, `.grupoNumero`, `.grupoMonto`, `.grupoSaldoOk`, `.grupoSaldoPendiente`, `.impInline*`, `.modal*`, `.btn*`, `.formGroup`, `.formRow`, `.formLabel`, `.textarea`, `.formActions`, `.modalHelp`, `.modalCloseBtn`)

**Acceptance criteria**:
- [ ] CC importa los 6 shared y los usa correctamente
- [ ] CC no tiene definidos `LedgerTable`, `EstadoPedidoBadge`, `MetricTile` internos (eliminados)
- [ ] CSS module del CC reducido (~800 líneas eliminadas, las clases migradas)
- [ ] **Diff visual manual**: comparar pantalla del CC pre y post — debe ser idéntico
  - Buscador + filtros
  - Hero card con monogram + 3 metric tiles
  - Quick actions chips
  - Vista cronológica (tabla con Debe/Haber/Saldo)
  - Vista por-pedido (cards colapsables)
  - Modales Pago Rápido + Ajuste Manual abren bien
  - Modo claro y oscuro
- [ ] ESLint clean
- [ ] Build clean
- [ ] No hay imports circulares

**PR1 título**: `refactor(compras): extraer componentes shared del módulo + refactor CC`

---

## Batch 2 — Pedidos (PR2)

> **Deps**: PR1 mergeado. Tasks T2.x son **secuenciales** (mismo PR), pero T2.2-T2.4 pueden empezarse después de T2.1 una vez que el patrón del tab esté validado.

### T2.1 — Rediseño TabPedidosCompra
**Size**: L · **Deps**: T1.7

**Files**:
- MODIFY `frontend/src/components/compras/TabPedidosCompra.jsx`
- MODIFY `frontend/src/components/compras/TabPedidosCompra.module.css`

**Action**:
1. Importar shared: `DataTable`, `EstadoBadge`, `EmptyState`, `LoadingBlock`, `FiltersBar`
2. Reemplazar `<table>` actual por `<DataTable>` con columns:
   - Número (font-mono)
   - Proveedor
   - Empresa
   - Moneda + Monto
   - Estado (`<EstadoBadge variant='pedido'>`)
   - Factura ERP (si aplica)
   - Fecha
   - Acciones (botones ver/editar/pagar/eliminar)
3. Filtros del topBar van dentro de `<FiltersBar>` con slot `actions={<button>Nuevo pedido</button>}`
4. Empty state con `<EmptyState tone='inline'>` en tabla, `<EmptyState tone='hero'>` si no hay proveedor seleccionado
5. Loading con `<LoadingBlock>`
6. Limpiar CSS module: eliminar clases reemplazadas por shared (table*, empty*, etc.)
7. Mantener clases específicas: filterProveedor, btnSuccess, iconBtn(Danger)?, paginación

**Acceptance criteria**:
- [ ] Tab consume los 5 shared correctamente
- [ ] Filtros (estado, empresa, proveedor, fechas, búsqueda) funcionan
- [ ] EstadoBadge muestra correctamente cada estado de pedido
- [ ] Acciones por fila (ver, editar, pagar, eliminar) preservadas
- [ ] Paginación funciona
- [ ] ESLint + build clean
- [ ] Modo claro/oscuro
- [ ] Mobile responsive

---

### T2.2 — Rediseño ModalPedidoDetalle
**Size**: L · **Deps**: T2.1 (ideal pero no obligatorio)

**Files**:
- MODIFY `frontend/src/components/compras/ModalPedidoDetalle.jsx`
- MODIFY `frontend/src/components/compras/ModalPedidoDetalle.module.css`

**Action**:
1. Header del modal con tipografía coherente: título `font-lg + font-bold`, close button consistente
2. EstadoBadge variant='pedido' en lugar del pill custom existente
3. Datos del pedido en tarjetas con tipografía monospace donde aplique (números, fechas)
4. Timeline (sección colapsable) **NO TOCAR la lógica** — solo aplicar tipografía coherente
5. Payload colapsable existente **PRESERVADO** intacto
6. Footer con botones coherentes (filter brightness en hover)

**Acceptance criteria**:
- [ ] Header + body + footer con coherencia visual del módulo
- [ ] Timeline + payload colapsable funcionan idéntico que antes
- [ ] EstadoBadge correcto
- [ ] Acciones (Corregir, Cancelar, etc.) funcionan
- [ ] Modo claro/oscuro
- [ ] ESLint clean

---

### T2.3 — Rediseño ModalPedidoCompra
**Size**: M · **Deps**: T2.1

**Files**:
- MODIFY `frontend/src/components/compras/ModalPedidoCompra.jsx`
- MODIFY `frontend/src/components/compras/ModalPedidoCompra.module.css`

**Action**: form con labels uppercase tracking 0.06em, buttons de submit con filter brightness en hover, help banner con border-left azul si hay (tipo "info").

**Acceptance criteria**:
- [ ] Labels coherentes
- [ ] Submit funciona (crear/editar pedido)
- [ ] Validaciones existentes preservadas
- [ ] ESLint clean

---

### T2.4 — Rediseño ModalCorregirPedido
**Size**: M · **Deps**: T2.1

**Files**:
- MODIFY `frontend/src/components/compras/ModalCorregirPedido.jsx`
- MODIFY `frontend/src/components/compras/ModalCorregirPedido.module.css`

**Action**: aplicar mismo lenguaje que T2.3. Mantener restricciones de campos editables (Feature B).

**Acceptance criteria**:
- [ ] Coherencia visual
- [ ] Funcionalidad de corregir pedido (clonación append-only) preservada
- [ ] ESLint clean

**PR2 título**: `feat(compras/pedidos): rediseño visual con shared components`

---

## Batch 3 — OPs (PR3)

> **Deps**: PR2 mergeado.

### T3.1 — Rediseño TabOrdenesPago
**Size**: L · **Deps**: PR2

**Files**:
- MODIFY `frontend/src/components/compras/TabOrdenesPago.jsx`
- MODIFY `frontend/src/components/compras/TabOrdenesPago.module.css`

**Action**: análogo a T2.1 con:
- Columns: Número (mono), Empresa, Proveedor, Modo (a_cuenta/especifica/mixta), Moneda + Monto, TC, Fecha pago real, Estado (`<EstadoBadge variant='op'>`), Acciones
- Filtros: estado, modo, empresa, proveedor, fechas
- Acciones por fila: ver, ejecutar pago (si pendiente), anular (si pagado), cancelar (si pendiente)

**Acceptance criteria**:
- [ ] Tab consume shared
- [ ] EstadoBadge variant='op' funciona (pagado/pendiente/anulado/cancelado)
- [ ] Acciones por fila preservadas
- [ ] ESLint + build clean

---

### T3.2 — Rediseño ModalOrdenPagoDetalle
**Size**: L · **Deps**: T3.1

**Files**:
- MODIFY `frontend/src/components/compras/ModalOrdenPagoDetalle.jsx`
- MODIFY `frontend/src/components/compras/ModalOrdenPagoDetalle.module.css`

**Action**: header coherente, EstadoBadge, secciones (datos OP, items imputados, pago info), Timeline si existe.

**Acceptance criteria**:
- [ ] Coherencia visual
- [ ] Drill-down a pedidos imputados funciona
- [ ] ESLint clean

---

### T3.3 — Rediseño ModalOrdenPagoNueva
**Size**: L · **Deps**: T3.1

**Files**:
- MODIFY `frontend/src/components/compras/ModalOrdenPagoNueva.jsx`
- MODIFY `frontend/src/components/compras/ModalOrdenPagoNueva.module.css`

**Action**: form de creación de OP con coherencia visual. Preservar lógica de items, cross-moneda, TC override.

**Acceptance criteria**:
- [ ] Form coherente
- [ ] Crear OP funciona en los 3 modos (a_cuenta, especifica, mixta)
- [ ] ESLint clean

---

### T3.4 — Rediseño ModalEjecutarPago
**Size**: M · **Deps**: T3.1

**Files**:
- MODIFY `frontend/src/components/compras/ModalEjecutarPago.jsx`
- MODIFY `frontend/src/components/compras/ModalEjecutarPago.module.css`

**Action**: form de ejecución (caja, fecha, TC override) con coherencia.

**Acceptance criteria**:
- [ ] Coherencia visual
- [ ] Ejecutar pago funciona
- [ ] ESLint clean

**PR3 título**: `feat(compras/op): rediseño visual con shared components`

---

## Batch 4 — NCs (PR4)

> **Deps**: PR3 mergeado. **Atención**: ModalNCLocalDetalle es 726 LOC con Timeline y payload — alto riesgo de regresión.

### T4.1 — Rediseño TabNCsLocales
**Size**: L · **Deps**: PR3

**Files**:
- MODIFY `frontend/src/components/compras/TabNCsLocales.jsx`
- MODIFY `frontend/src/components/compras/TabNCsLocales.module.css`

**Action**: análogo a T3.1 con `<EstadoBadge variant='nc'>`. Acciones por fila: ver, aprobar (si pendiente_aprobacion), rechazar, cancelar, aplicar (si aprobado), vincular factura ERP.

**Acceptance criteria**:
- [ ] Tab consume shared
- [ ] EstadoBadge variant='nc' funciona (los 7 estados)
- [ ] Workflow completo preservado
- [ ] ESLint + build clean

---

### T4.2 — Rediseño ModalNCLocalDetalle (alto riesgo)
**Size**: XL · **Deps**: T4.1

**Files**:
- MODIFY `frontend/src/components/compras/ModalNCLocalDetalle.jsx` (726 LOC)
- MODIFY `frontend/src/components/compras/ModalNCLocalDetalle.module.css`

**Action**:
1. Header + body + footer con coherencia
2. **PRESERVAR** Timeline colapsable
3. **PRESERVAR** payload JSON colapsable dentro de cada evento
4. EstadoBadge variant='nc'
5. Sección de factura ERP vinculada con tipografía mono para números

**Acceptance criteria**:
- [ ] Coherencia visual con resto de modales
- [ ] Timeline funciona idéntico
- [ ] Payload JSON colapsable funciona
- [ ] Acciones (aplicar, vincular, cancelar) funcionan
- [ ] **Testing manual extra**: abrir NC con muchos eventos y verificar Timeline
- [ ] Modo claro/oscuro
- [ ] ESLint clean

---

### T4.3 — Rediseño ModalNCLocal (creación)
**Size**: M · **Deps**: T4.1

**Files**:
- MODIFY `frontend/src/components/compras/ModalNCLocal.jsx`
- MODIFY `frontend/src/components/compras/ModalNCLocal.module.css`

**Action**: form de creación con coherencia.

**Acceptance criteria**:
- [ ] Crear NC funciona
- [ ] Coherencia visual
- [ ] ESLint clean

---

### T4.4 — Rediseño ModalAplicarNC
**Size**: M · **Deps**: T4.1

**Files**:
- MODIFY `frontend/src/components/compras/ModalAplicarNC.jsx`
- MODIFY `frontend/src/components/compras/ModalAplicarNC.module.css`

**Action**: aplicar NC a destino (pedido_compra / factura_erp / saldo). Preservar lógica de cada destino.

**Acceptance criteria**:
- [ ] Los 3 destinos funcionan (pedido, factura_erp, saldo)
- [ ] Coherencia visual
- [ ] ESLint clean

---

### T4.5 — Rediseño ModalVincularFacturaNC
**Size**: M · **Deps**: T4.1

**Files**:
- MODIFY `frontend/src/components/compras/ModalVincularFacturaNC.jsx`
- MODIFY `frontend/src/components/compras/ModalVincularFacturaNC.module.css`

**Action**: vincular NC a factura ERP existente con coherencia.

**Acceptance criteria**:
- [ ] Vincular funciona
- [ ] Coherencia visual
- [ ] ESLint clean

**PR4 título**: `feat(compras/nc): rediseño visual con shared components`

---

## Batch 5 — Admin (PR5)

> **Deps**: PR4 mergeado.

### T5.1 — Rediseño TabReconciliacion (con MetricTile)
**Size**: L · **Deps**: PR4

**Files**:
- MODIFY `frontend/src/components/compras/TabReconciliacion.jsx`
- MODIFY `frontend/src/components/compras/TabReconciliacion.module.css`

**Action**:
1. Header con título + botón "Forzar reconciliación" (si tiene permiso)
2. **4 métricas** arriba como `<MetricTile>` (proveedores procesados, divergencias, etc.)
3. `<DataTable>` para logs con columns: fecha, proveedor, moneda, divergencias_count, status
4. `<FiltersBar>` con date range + checkbox "solo divergencias"
5. Empty state si no hay logs

**Acceptance criteria**:
- [ ] 4 métricas como MetricTile con tone apropiado
- [ ] Tabla de logs funciona
- [ ] Filtros funcionan
- [ ] Forzar reconciliación funciona
- [ ] ESLint clean

---

### T5.2 — Rediseño TabSaleDocumentCatalog
**Size**: M · **Deps**: PR4

**Files**:
- MODIFY `frontend/src/components/compras/TabSaleDocumentCatalog.jsx`
- MODIFY `frontend/src/components/compras/TabSaleDocumentCatalog.module.css`

**Action**: tab admin simple. DataTable + filtros (clasificación, búsqueda) + sección "faltantes" con visual distinto (warning).

**Acceptance criteria**:
- [ ] Tabla de catálogo funciona
- [ ] Sección faltantes destacada
- [ ] ESLint clean

---

### T5.3 — Rediseño TabPapelera
**Size**: M · **Deps**: PR4

**Files**:
- MODIFY `frontend/src/components/compras/TabPapelera.jsx`
- MODIFY `frontend/src/components/compras/TabPapelera.module.css`

**Action**: DataTable con elementos eliminados, columna "tipo" con badge, acción restaurar. Filtro por tipo.

**Acceptance criteria**:
- [ ] Tabla funciona
- [ ] Restaurar funciona
- [ ] Filtro tipo funciona
- [ ] ESLint clean

---

### T5.4 — Rediseño PanelImputaciones
**Size**: L · **Deps**: PR4

**Files**:
- MODIFY `frontend/src/components/compras/PanelImputaciones.jsx`
- MODIFY `frontend/src/components/compras/PanelImputaciones.module.css`

**Action**:
1. DataTable con columns: fecha, origen → destino, monto, moneda, badge reversal/normal, acciones (desimputar, reimputar)
2. **Verificar** que el render inline en CC (cuando se usa con `proveedorIdFijo`) sigue siendo coherente
3. Modales internos (ModalConfirmarDesimputacion, ModalReimputar) coherentes

**Acceptance criteria**:
- [ ] PanelImputaciones funciona standalone (TabReconciliacion no lo usa, pero verificar imports)
- [ ] PanelImputaciones inline en CC sigue funcionando IDÉNTICO
- [ ] Acciones desimputar/reimputar OK
- [ ] ESLint clean
- [ ] **Testing manual**: abrir CC, expandir Imputaciones inline, verificar visual; navegar al PanelImputaciones standalone si tiene tab dedicado

---

### T5.5 — Rediseño ModalConfirmarEliminacion
**Size**: S · **Deps**: PR4

**Files**:
- MODIFY `frontend/src/components/compras/ModalConfirmarEliminacion.jsx`
- MODIFY `frontend/src/components/compras/ModalConfirmarEliminacion.module.css`

**Action**: modal genérico de confirmación con coherencia (header, body, footer con btnDanger).

**Acceptance criteria**:
- [ ] Coherencia visual
- [ ] Confirmación funciona en todos los contextos donde se usa
- [ ] ESLint clean

---

### T5.6 — Rediseño ModalVincularFactura
**Size**: M · **Deps**: PR4

**Files**:
- MODIFY `frontend/src/components/compras/ModalVincularFactura.jsx`
- MODIFY `frontend/src/components/compras/ModalVincularFactura.module.css`

**Action**: vincular factura ERP a pedido (el equivalente para pedidos del ModalVincularFacturaNC). Coherencia visual.

**Acceptance criteria**:
- [ ] Vincular funciona
- [ ] Coherencia visual
- [ ] ESLint clean

**PR5 título**: `feat(compras/admin): rediseño visual con shared components`

---

## Resumen

| Batch | PR | Tasks | Size total | Paralelizable internamente |
|---|---|---|---|---|
| 0 | tokens | T0.1 | S | N/A |
| 1 | shared | T1.1-T1.7 | L+M×4+S×2+L | T1.1-T1.6 sí, T1.7 después |
| 2 | pedidos | T2.1-T2.4 | L+L+M+M | T2.1 primero, T2.2-T2.4 después |
| 3 | ops | T3.1-T3.4 | L+L+L+M | T3.1 primero, T3.2-T3.4 después |
| 4 | ncs | T4.1-T4.5 | L+XL+M+M+M | T4.1 primero, T4.2-T4.5 después |
| 5 | admin | T5.1-T5.6 | L+M+M+L+S+M | T5.1-T5.6 paralelizables |

**Total tasks**: 27
**Total estimado**: 8-12 horas-foco (depende del cuidado en testing manual visual).

## Implementation Order

Estricto: **PR0 → PR1 → PR2 → PR3 → PR4 → PR5**.

Dentro de cada PR:
- PR1: T1.1-T1.6 en paralelo, después T1.7
- PR2-PR4: tab primero, modales después (idealmente en commits separados dentro del mismo PR)
- PR5: tasks paralelizables (no hay dependencia entre TabReconciliacion / SaleDoc / Papelera / Imputaciones / Modales)

## Pause Points

- **Después de PR1**: validar con user que los shared funcionan visualmente bien y que el CC mantiene el look. Si algo no convence → ajustar antes de PR2.
- **Después de PR2**: validar que el patrón aplicado a un dominio nuevo (lista plana de pedidos) se ve coherente con el CC. Si no convence → pausar PRs 3-5 hasta resolver.
