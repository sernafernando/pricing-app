# Design: compras-redesign-tabs

## Technical Approach

**Estrategia**: extraer 6 componentes shared del `TabCCProveedores` ya rediseñado, refactorizar el CC para consumirlos sin cambio visual (PR1), después aplicar progresivamente a los 4 dominios restantes (PR2-5). Tokens nuevos en commit prerequisito (PR0).

**Mapping con specs**:
- `ui-shared-components` → 6 archivos JSX + CSS Module en `_shared/` con API documentada vía JSDoc
- `design-tokens-finance` → 4 tokens aditivos en `design-tokens.css`
- `compras-visual-coherence` → garantizada por construcción: todos los tabs consumen los mismos shared

## Architecture Decisions

### Decision: Estructura del directorio `_shared/`

**Choice**: `frontend/src/components/compras/_shared/` con archivos `PascalCase.jsx` + `PascalCase.module.css` por componente. **Sin barrel export** (`index.js`), imports directos.

**Alternatives considered**:
1. `frontend/src/components/_shared/` (genérico) — descartado: los componentes son específicos del dominio compras (EstadoBadge.variant='nc' no aplica fuera). Si se hace genérico en el futuro, se mueven.
2. Barrel export `_shared/index.js` con re-exports — descartado: el resto del proyecto importa directo (`import X from './Component'`), no hay precedente. Barrel agrega indirection sin beneficio claro.
3. `frontend/src/components/compras/shared/` (sin `_`) — descartado: el `_` lo distingue como "infra/util" y lo separa visualmente al ordenar archivos en file explorer.

**Rationale**: coherente con la convención existente del proyecto (sin barrel, sin alias paths, components co-localizados con CSS Modules). El prefijo `_` deja claro que es infraestructura interna.

### Decision: JSDoc + sin PropTypes

**Choice**: Documentar props con JSDoc al inicio de cada componente. NO usar `prop-types`, NO migrar a TypeScript en este change.

**Alternatives considered**:
1. Agregar `prop-types` package — descartado: introduce dependencia nueva (contra restricción), poco valor comparado con TypeScript.
2. Migrar a TypeScript — descartado: out-of-scope explícito en proposal.

**Rationale**: JSDoc es zero-dependency, lo lee el IDE para autocompletion, y es coherente con el resto del proyecto que también usa JSDoc.

### Decision: Refactor del CC en PR1 con "cero cambio visual"

**Choice**: el PR1 refactoriza `TabCCProveedores.jsx` y `TabCCProveedores.module.css` para consumir los nuevos shared. Las clases CSS migradas se **eliminan** del module del CC (no se duplican). Para verificar "cero cambio visual" se hace **diff visual manual** comparando la pantalla del CC pre-merge vs post-merge en local.

**Alternatives considered**:
1. Mantener clases en CC + duplicar en shared — descartado: duplica deuda inmediatamente, contradice la razón de extraer.
2. Tests de snapshot CSS — descartado: el proyecto no tiene infra de visual regression. Setearla es proyecto aparte.
3. Capturas con Playwright — descartado: no hay E2E configurado, agregarlo es scope mayor.

**Rationale**: pragmático para el contexto. El PR1 es revisable visualmente en local; si algo cambia, se nota inmediato. La validación manual es suficiente porque el usuario ya conoce el look del CC.

**Verificación concreta para PR1**:
- Antes del refactor: tomar screenshot de `TabCCProveedores` con un proveedor cargado (vista cronológica + por-pedido + modales abiertos).
- Después del refactor: tomar mismo screenshot, comparar pixel-perfect (al menos visualmente).
- Si hay diferencias: ajustar shared para preservar look exacto.

### Decision: API de DataTable con `renderCell`

**Choice**: `DataTable` recibe `columns` (config) + `rows` (data) + `renderCell(row, column)` (custom render). Cada column tiene `{ key, label, align, width }`. La column.width se aplica vía `<colgroup>`.

**Alternatives considered**:
1. Render props en cada column (`column.render = (row) => ...`) — descartado: complica el shape del array de columns y dificulta serializar.
2. Children render-prop pattern (`<DataTable>{(row) => ...}</DataTable>`) — descartado: menos descubrible, requiere más boilerplate.

**Rationale**: `renderCell(row, column)` es el patrón que ya usa LedgerTable interno del CC. Continuidad y simplicidad.

### Decision: EstadoBadge mapping completo

**Choice**: tabla de mapping fija (no extensible runtime), implementada como objeto JS const al top del componente. Variants documentadas y validadas en runtime con fallback a "Desconocido".

**Mapping por variant**:

#### `variant="pedido"` (basado en `PedidoCompra.estado`)

| Estado backend | Saldo | Tono visual | Label | Ícono |
|---|---|---|---|---|
| `pagado` | =0 | verde | Pagado | CheckCircle2 |
| `pagado_parcial` | =0 | verde | Pagado | CheckCircle2 |
| `pagado_parcial` | >0 | amarillo | Parcial | Clock |
| `aprobado` | * | naranja | Pendiente | CircleAlert |
| `pendiente_aprobacion` | * | gris suave | Sin aprobar | Clock |
| `borrador` | * | gris suave | Borrador | Clock |
| `rechazado` | * | gris | Rechazado | X |
| `cancelado` | * | gris | Cancelado | X |

#### `variant="op"` (basado en `OrdenPago.estado`)

| Estado backend | Tono visual | Label | Ícono |
|---|---|---|---|
| `pagado` | verde | Pagada | CheckCircle2 |
| `pendiente` | naranja | Pendiente | Clock |
| `anulado` | gris | Anulada | X |
| `cancelado` | gris | Cancelada | X |

#### `variant="nc"` (basado en `NotaCreditoLocal.estado`)

| Estado backend | Tono visual | Label | Ícono |
|---|---|---|---|
| `aplicada` | verde | Aplicada | CheckCircle2 |
| `aplicada_parcial` | amarillo | Parcial | Clock |
| `aprobado` | naranja | Aprobada | CircleAlert |
| `pendiente_aprobacion` | gris suave | Sin aprobar | Clock |
| `borrador` | gris suave | Borrador | Clock |
| `rechazado` | gris | Rechazada | X |
| `cancelado` | gris | Cancelada | X |

**Rationale**: el backend ya valida estados en `CheckConstraint` — el mapping del frontend es un superset reflejo de los estados válidos. Si se agrega un estado nuevo en el backend, el badge cae en fallback "Desconocido" hasta que se actualice el mapping (degradación elegante).

### Decision: Layout responsive con breakpoints existentes

**Choice**: usar los breakpoints que ya existen en el módulo (768px y 600px). DataTable con `min-width: 720px` + scroll-x cuando overflow. MetricTile grid con `repeat(auto-fit, minmax(200px, 1fr))`. FiltersBar con `flex-wrap: wrap`.

**Breakpoints**:
- **mobile** (<600px): MetricTile en 1 columna, hero card colapsa stack vertical
- **tablet** (600-1024px): MetricTile 2 columnas, hero card grid 1+1
- **desktop** (>1024px): MetricTile 3 columnas, hero card grid 1+2

**DataTable comportamiento**:
- En mobile: scroll horizontal con shadow gradient en bordes (indicador visual)
- En desktop: full width sin scroll

**Modales**:
- En mobile: `width: 100%`, padding `var(--spacing-md)`
- En desktop: `max-width: 560px` (form) o `720px` (detalle)

**Rationale**: respetar lo que ya funciona en el CC. No introducir breakpoints nuevos.

### Decision: Imports relativos sin alias

**Choice**: usar paths relativos (`import DataTable from './_shared/DataTable'`) desde tabs del módulo compras. NO configurar alias en `vite.config.js`.

**Alternatives considered**:
1. Agregar alias `@compras-shared` en vite — descartado: el proyecto no usa alias en ningún lado, agregar uno solo para este caso es inconsistente.
2. Imports absolutos desde `src/` — descartado: idem.

**Rationale**: coherencia con el resto del proyecto. Los tabs y `_shared/` están en el mismo directorio padre, los relative paths son cortos (`./_shared/X`).

## Data Flow

```
                      ┌──────────────────────────────────┐
                      │  frontend/src/styles/             │
                      │  design-tokens.css                │
                      │  (--cf-* + 4 tokens nuevos)       │
                      └─────────────┬────────────────────┘
                                    │ consumed via var()
                                    ▼
    ┌───────────────────────────────────────────────────┐
    │  frontend/src/components/compras/_shared/         │
    │                                                   │
    │  DataTable.jsx ◄── EmptyState.jsx                 │
    │      │              ▲                             │
    │      │              │ render slot                 │
    │      ▼                                            │
    │  LoadingBlock.jsx                                 │
    │                                                   │
    │  EstadoBadge.jsx (3 variants: pedido/op/nc)       │
    │  MetricTile.jsx                                   │
    │  FiltersBar.jsx                                   │
    └─────────────┬─────────────────────────────────────┘
                  │ imported by tabs
                  ▼
    ┌───────────────────────────────────────────────────┐
    │  Tabs del módulo compras                          │
    │                                                   │
    │  PR1: TabCCProveedores  ──► consume shared        │
    │  PR2: TabPedidosCompra  ──► consume shared        │
    │  PR3: TabOrdenesPago    ──► consume shared        │
    │  PR4: TabNCsLocales     ──► consume shared        │
    │  PR5: TabReconciliacion ──► consume MetricTile    │
    │       TabSaleDocumentCatalog                      │
    │       TabPapelera                                 │
    │       PanelImputaciones                           │
    └───────────────────────────────────────────────────┘
```

**Reglas de import**:
- Los tabs importan de `./_shared/X` (path relativo)
- Los componentes en `_shared/` NO importan de `Tab*`, `Modal*`, `Panel*` (ESLint `import/no-cycle`)
- Los componentes en `_shared/` PUEDEN importar entre sí (DataTable usa EmptyState + LoadingBlock)

## File Changes

### PR0 — Tokens (commit prerequisito)

| File | Action | Description |
|---|---|---|
| `frontend/src/styles/design-tokens.css` | Modify | +4 tokens: `--cf-shadow-card`, `--cf-shadow-modal`, `--font-mono` formal, `--cf-saldo-positive`, `--cf-saldo-negative` |

**Líneas estimadas**: +30, ~0 modificadas, 0 eliminadas.

### PR1 — Shared + refactor CC

| File | Action | Description |
|---|---|---|
| `frontend/src/components/compras/_shared/DataTable.jsx` | Create | Tabla unificada con colgroup + slots |
| `frontend/src/components/compras/_shared/DataTable.module.css` | Create | Estilos extraídos del CC |
| `frontend/src/components/compras/_shared/EstadoBadge.jsx` | Create | Variants pedido/op/nc |
| `frontend/src/components/compras/_shared/EstadoBadge.module.css` | Create | 5 tonos + base |
| `frontend/src/components/compras/_shared/EmptyState.jsx` | Create | icon + title + subtitle + cta opcional |
| `frontend/src/components/compras/_shared/EmptyState.module.css` | Create | Tones hero/inline/default |
| `frontend/src/components/compras/_shared/MetricTile.jsx` | Create | 4 tones + striped pattern |
| `frontend/src/components/compras/_shared/MetricTile.module.css` | Create | Border-left coloreado |
| `frontend/src/components/compras/_shared/LoadingBlock.jsx` | Create | Spinner azul + texto |
| `frontend/src/components/compras/_shared/LoadingBlock.module.css` | Create | Animation spin |
| `frontend/src/components/compras/_shared/FiltersBar.jsx` | Create | Slot children + actions |
| `frontend/src/components/compras/_shared/FiltersBar.module.css` | Create | Flex-wrap responsive |
| `frontend/src/components/compras/TabCCProveedores.jsx` | Modify | Refactor para consumir shared |
| `frontend/src/components/compras/TabCCProveedores.module.css` | Modify | Remover clases que migran a shared |

**Líneas estimadas**: +1.500 (shared), -800 (clases migradas del CC), +50 (imports/usage en CC). Net: +750.

### PR2 — Pedidos

| File | Action | Description |
|---|---|---|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modify | Consume DataTable + EstadoBadge variant=pedido + EmptyState + LoadingBlock + FiltersBar |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modify | Limpiar clases reemplazadas; mantener solo lo específico |
| `frontend/src/components/compras/ModalPedidoDetalle.jsx` | Modify | Header + body con tipografía coherente, EstadoBadge en lugar de pill custom |
| `frontend/src/components/compras/ModalPedidoDetalle.module.css` | Modify | Coherencia visual con CC |
| `frontend/src/components/compras/ModalPedidoCompra.jsx` | Modify | Form labels uppercase, buttons coherentes |
| `frontend/src/components/compras/ModalPedidoCompra.module.css` | Modify | Idem |
| `frontend/src/components/compras/ModalCorregirPedido.jsx` | Modify | Coherencia visual |
| `frontend/src/components/compras/ModalCorregirPedido.module.css` | Modify | Idem |

**Líneas estimadas**: ~700 modificadas, ~300 eliminadas (CSS stale).

### PR3 — OPs

| File | Action | Description |
|---|---|---|
| `frontend/src/components/compras/TabOrdenesPago.{jsx,module.css}` | Modify | Idem PR2 con variant=op |
| `frontend/src/components/compras/ModalOrdenPagoDetalle.{jsx,module.css}` | Modify | Idem |
| `frontend/src/components/compras/ModalOrdenPagoNueva.{jsx,module.css}` | Modify | Idem |
| `frontend/src/components/compras/ModalEjecutarPago.{jsx,module.css}` | Modify | Idem |

**Líneas estimadas**: ~800 modificadas.

### PR4 — NCs

| File | Action | Description |
|---|---|---|
| `frontend/src/components/compras/TabNCsLocales.{jsx,module.css}` | Modify | Idem con variant=nc |
| `frontend/src/components/compras/ModalNCLocalDetalle.{jsx,module.css}` | Modify | Atención a Timeline + payload colapsable (alto riesgo regresión) |
| `frontend/src/components/compras/ModalNCLocal.{jsx,module.css}` | Modify | Coherencia |
| `frontend/src/components/compras/ModalAplicarNC.{jsx,module.css}` | Modify | Coherencia |
| `frontend/src/components/compras/ModalVincularFacturaNC.{jsx,module.css}` | Modify | Coherencia |

**Líneas estimadas**: ~900 modificadas.

### PR5 — Admin

| File | Action | Description |
|---|---|---|
| `frontend/src/components/compras/TabReconciliacion.{jsx,module.css}` | Modify | Métricas con MetricTile (4 cards arriba) |
| `frontend/src/components/compras/TabSaleDocumentCatalog.{jsx,module.css}` | Modify | DataTable + filtros |
| `frontend/src/components/compras/TabPapelera.{jsx,module.css}` | Modify | DataTable + restaurar |
| `frontend/src/components/compras/PanelImputaciones.{jsx,module.css}` | Modify | DataTable + acciones inline |
| `frontend/src/components/compras/ModalConfirmarEliminacion.{jsx,module.css}` | Modify | Coherencia modal |
| `frontend/src/components/compras/ModalVincularFactura.{jsx,module.css}` | Modify | Coherencia modal |

**Líneas estimadas**: ~700 modificadas.

## Interfaces / Contracts

### DataTable

```jsx
/**
 * @typedef {Object} ColumnDef
 * @property {string} key - identificador único de la columna
 * @property {string} label - texto del header
 * @property {'left'|'right'|'center'} [align='left']
 * @property {string} [width] - CSS width (ej. '92px', '1fr', 'auto')
 */

/**
 * @param {Object} props
 * @param {ColumnDef[]} props.columns
 * @param {Object[]} props.rows - cada row debe tener un id único
 * @param {(row, column) => ReactNode} props.renderCell
 * @param {boolean} [props.loading=false]
 * @param {{icon: ReactNode, title: string, subtitle?: string, cta?: {label, onClick, variant?}}} [props.empty]
 * @param {(row) => void} [props.onRowClick]
 * @param {(row) => boolean} [props.navegableRowFn]
 * @param {string} [props.minWidth='720px']
 */
export default function DataTable({ columns, rows, renderCell, loading, empty, onRowClick, navegableRowFn, minWidth }) { ... }
```

### EstadoBadge

```jsx
/**
 * @param {Object} props
 * @param {'pedido'|'op'|'nc'} props.variant
 * @param {string} props.estado - estado del entity backend
 * @param {number} [props.saldo] - solo para variant=pedido
 * @param {'sm'|'md'} [props.size='sm']
 */
export default function EstadoBadge({ variant, estado, saldo, size }) { ... }
```

### EmptyState

```jsx
/**
 * @param {Object} props
 * @param {ReactNode} props.icon - típicamente <Icon size={28-36} />
 * @param {string} props.title
 * @param {string} [props.subtitle]
 * @param {{label: string, onClick: () => void, variant?: 'primary'|'secondary'}} [props.cta]
 * @param {'default'|'inline'|'hero'} [props.tone='default']
 */
export default function EmptyState({ icon, title, subtitle, cta, tone }) { ... }
```

### MetricTile

```jsx
/**
 * @param {Object} props
 * @param {string} props.label
 * @param {string|number} props.value
 * @param {string} [props.hint]
 * @param {'debe'|'haber'|'neutral'|'estimate'} [props.tone='neutral']
 * @param {ReactNode} [props.icon] - override del default por tone
 */
export default function MetricTile({ label, value, hint, tone, icon }) { ... }
```

### LoadingBlock

```jsx
/**
 * @param {Object} props
 * @param {string} [props.text='Cargando…']
 * @param {'block'|'inline'} [props.tone='block']
 */
export default function LoadingBlock({ text, tone }) { ... }
```

### FiltersBar

```jsx
/**
 * @param {Object} props
 * @param {ReactNode} props.children - filtros (selects, date pickers, etc.)
 * @param {ReactNode} [props.actions] - botones primarios alineados a la derecha
 */
export default function FiltersBar({ children, actions }) { ... }
```

## Migración de CSS classes

Tabla de mapping de clases del CC actual a sus destinos en shared:

| Clase en `TabCCProveedores.module.css` | Destino |
|---|---|
| `.tableWrapper`, `.table`, `.colFecha`, `.colOrigen`, `.colNum`, `.colMon`, `.colAccion`, `.thLeft`, `.thRight`, `.thCenter`, `.tdSecondary`, `.tdMoneda`, `.tdAccion`, `.tdRightDebe`, `.tdRightHaber`, `.tdRightSaldo`, `.rowClickable`, `.iconBtn` | `_shared/DataTable.module.css` |
| `.estadoBadge`, `.estadoPagado`, `.estadoParcial`, `.estadoPendiente`, `.estadoCancelado`, `.estadoBorrador`, `.badgeDebe`, `.badgeHaber`, `.badgeAjuste` | `_shared/EstadoBadge.module.css` |
| `.heroEmpty`, `.heroEmptyIcon`, `.heroEmptyTitle`, `.heroEmptySub`, `.emptyRow`, `.emptyRowInner`, `.emptyBlock` | `_shared/EmptyState.module.css` |
| `.metricTile`, `.metricTileDebe`, `.metricTileHaber`, `.metricTileNeutral`, `.metricTileEstimate`, `.metricLabelRow`, `.metricLabel`, `.metricValue`, `.metricHint` | `_shared/MetricTile.module.css` |
| `.heroLoading`, `.heroLoadingText`, `.spin`, `.centered` | `_shared/LoadingBlock.module.css` |
| `.searchBar`, `.searchProveedor`, `.input`, `.select`, `.errorBanner` | **Quedan en CC** (no son shared, son específicos del CC) |
| Resto (hero, monogram, accionesBar, actionChip*, viewSwitcher, ledgerToolbar, grupoCard*, impInline*, modal*, btn*) | **Quedan en CC** o se mueven en PRs siguientes |

**Cleanup post-migración**: las clases listadas a la izquierda se ELIMINAN del module del CC en el PR1.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit (visual JSX) | Renderizado de cada shared con props variados | Manual visual en `npm run dev` con stories ad-hoc en una página de prueba (no se commitea) |
| Integration (tab flow) | Cada tab con sus modales y filtros funciona end-to-end | Manual: probar cada flujo crítico (crear pedido, aprobar, pagar, anular, eliminar) |
| Regression (no cambio funcional) | 100% de los handlers/hooks intactos | Code review + diff cuidadoso de PRs |
| Build | `npm run build` sin errores ni warnings nuevos | Pre-merge gate |
| ESLint | `npx eslint frontend/src/components/compras/` clean | Pre-merge gate |

### Checklist por PR

**PR0 (tokens)**:
- [ ] Variables nuevas presentes en `design-tokens.css` en `:root` y `:root[data-theme="light"]`
- [ ] `npm run build` clean
- [ ] Verificar visual en cualquier módulo no-compras: nada cambió

**PR1 (shared)**:
- [ ] 6 archivos JSX + 6 CSS Modules en `_shared/`
- [ ] Cada componente con JSDoc completo
- [ ] CC consume todos los shared aplicables
- [ ] Diff visual del CC pre/post: idéntico (5 secciones a verificar: search bar, hero card, metric tiles, ledger table, modales)
- [ ] ESLint clean
- [ ] Build clean
- [ ] Modo claro y oscuro

**PR2 (pedidos)**:
- [ ] TabPedidosCompra usa DataTable + EstadoBadge variant=pedido + EmptyState + LoadingBlock + FiltersBar
- [ ] Filtros (estado, empresa, proveedor, fechas, búsqueda) funcionan
- [ ] Crear pedido (Modal) → flujo completo OK
- [ ] Editar pedido → OK
- [ ] Aprobar → estado cambia, badge se actualiza
- [ ] Pagar (drill-down a OP) → OK
- [ ] Eliminar → modal de confirmación → papelera
- [ ] Modo claro/oscuro
- [ ] Mobile (<768px): responsive funciona

**PR3 (ops)**:
- [ ] TabOrdenesPago coherente
- [ ] EstadoBadge variant=op muestra Pagada/Pendiente/Anulada/Cancelada
- [ ] Crear OP → OK
- [ ] Ejecutar pago → OK
- [ ] Anular → OK
- [ ] Cancelar pendiente → OK

**PR4 (ncs)**:
- [ ] TabNCsLocales coherente
- [ ] EstadoBadge variant=nc cubre los 7 estados
- [ ] Crear NC → OK
- [ ] Aprobar → OK
- [ ] Aplicar a factura ERP → OK
- [ ] Vincular factura ERP → OK
- [ ] **ATENCIÓN**: Timeline en ModalNCLocalDetalle (726 LOC) — verificar que el `<details>` colapsable y el payload JSON sigan funcionando

**PR5 (admin)**:
- [ ] TabReconciliacion muestra 4 métricas como MetricTile
- [ ] TabSaleDocumentCatalog filtros + tabla
- [ ] TabPapelera lista + restaurar
- [ ] PanelImputaciones standalone funciona igual que inline en CC
- [ ] ModalConfirmarEliminacion + ModalVincularFactura coherentes

## Migration / Rollout

**No data migration required** (todo es frontend visual).

**Feature flags**: NO. Cada PR es atómico — al mergearse, el cambio aplica inmediatamente al módulo.

**Rollout phasing**: secuencial PR0 → PR1 → PR2 → PR3 → PR4 → PR5. Mergear sin rush; el usuario valida cada PR antes del siguiente.

**Pause points**: si PR2 (pedidos) no convence visualmente al usuario, **pausar PRs 3-5** hasta resolver feedback. PRs 0+1 son base estructural y siguen funcionando.

**Coordinación con otros desarrollos en el módulo**: si durante el rediseño el usuario pide un bugfix urgente en pedidos/ops/ncs, ese fix se hace en `develop` directo y se rebasea contra el PR de rediseño.

## Open Questions

- [ ] ¿La pantalla de prueba ad-hoc para validar shared (sub-bullet de "Unit testing") se commitea como parte del PR1 o queda local-only? **Default**: local-only, no se commitea.
- [ ] ¿El cleanup de `frontend/src/components/SearchInput.jsx` (componente global existente) entra en este change? **Default**: NO, queda como está. SearchInput es genérico de toda la app, no del módulo compras.
- [ ] ¿En PR5 (admin) el rediseño de `PanelImputaciones` afecta el render inline en CC del PR1? **Respuesta**: SÍ, porque CC importa PanelImputaciones. Si PR5 cambia visualmente PanelImputaciones, hay que verificar el doble uso en CC también. Plan: en PR1 NO se cambia PanelImputaciones (se deja para PR5); en PR5 se valida inline + standalone.
