# UI Shared Components — Compras

## Purpose

Define el contrato de los componentes de UI compartidos del módulo compras, ubicados en `frontend/src/components/compras/_shared/`. Estos componentes encapsulan los patrones visuales validados en `TabCCProveedores` y se reutilizan en los demás tabs/paneles/modales del módulo.

Cada componente expone una API de props estable, soporta variantes documentadas, y mantiene coherencia visual con los design tokens `--cf-*`.

## Requirements

### Requirement: DataTable component

El componente `DataTable` SHALL ser una tabla unificada con anchos de columna estables, tipografía tabular para números, hover con accent lateral en filas navegables, y slots para estados de empty/loading.

**Props API**:
- `columns` (array, required): array de `{ key, label, align: 'left'|'right'|'center', width?: string }`. `width` se aplica vía `<colgroup>`.
- `rows` (array, required): array de objetos a renderear. Cada row debe tener un `id` único.
- `renderCell` (function, required): `(row, column) => ReactNode` para custom rendering por celda.
- `loading` (boolean): muestra `<LoadingBlock />` si `true`.
- `empty` (object): `{ icon, title, subtitle, cta? }` mostrado cuando `rows.length === 0` y `!loading`.
- `onRowClick` (function, optional): `(row) => void`. Si está presente, la fila tiene `cursor: pointer` y muestra accent lateral en hover.
- `navegableRowFn` (function, optional): `(row) => boolean` — predicado para activar `cursor: pointer` por fila.
- `minWidth` (string): default `720px`. La tabla tiene `min-width` y scroll-x cuando overflow.

#### Scenario: tabla con datos y columnas con anchos fijos

- GIVEN un DataTable con `columns=[{key:'fecha', label:'Fecha', width:'92px'}, {key:'monto', label:'Monto', align:'right', width:'156px'}]` y 5 rows
- WHEN el componente se monta
- THEN el `<table>` tiene `table-layout: fixed`, contiene un `<colgroup>` con `<col>` de los widths declarados
- AND los headers tienen `text-align` según el `align` de cada column
- AND los valores numéricos heredan `font-variant-numeric: tabular-nums` y `font-family: var(--font-mono)`

#### Scenario: tabla vacía con empty slot

- GIVEN un DataTable con `rows=[]`, `loading=false`, `empty={icon: <Icon/>, title: 'Sin movimientos', subtitle: 'No hay datos en este periodo.'}`
- WHEN el componente se monta
- THEN el `<tbody>` renderea una sola `<tr>` con `<td colSpan={columns.length}>` que contiene un `<EmptyState />` con los props pasados
- AND ningún row de datos se renderea

#### Scenario: tabla loading

- GIVEN un DataTable con `loading=true`
- WHEN el componente se monta
- THEN se muestra `<LoadingBlock />` en lugar de la tabla, o como overlay sobre el `<tbody>`
- AND no se intenta renderear `rows`

#### Scenario: row navegable con accent lateral

- GIVEN un DataTable con `onRowClick` y `navegableRowFn={(row) => row.tipo === 'pedido'}`
- WHEN el usuario hace hover sobre una row con `tipo='pedido'`
- THEN la fila muestra un accent lateral (border-left de `--cf-accent-blue`) animado vía `transform: scaleY()`
- AND `cursor: pointer` está activo
- AND al hacer click se invoca `onRowClick(row)`

### Requirement: EstadoBadge component

El componente `EstadoBadge` SHALL renderear un badge visual de estado con 5 tonos consistentes (Pagado verde, Parcial amarillo, Pendiente naranja, Cancelado gris, Borrador gris suave) y soportar variantes por workflow (pedido, op, nc).

**Props API**:
- `variant` (string, required): `'pedido' | 'op' | 'nc'`. Define el mapping estado→tono.
- `estado` (string, required): el estado del entity (ej. `'pagado'`, `'pendiente_aprobacion'`, `'aplicada_parcial'`).
- `saldo` (number, optional): solo aplica a `variant='pedido'`. Si `saldo===0` y estado es pagado/pagado_parcial, se muestra como "Pagado" verde.
- `size` (string): `'sm' | 'md'`. Default `'sm'`.

**Mapping por variant**:
- `pedido`: `pagado`/`pagado_parcial`+saldo=0 → Pagado · `pagado_parcial`+saldo>0 → Parcial · `aprobado`/`pendiente_aprobacion` → Pendiente · `cancelado`/`rechazado` → Cancelado · `borrador` → Borrador
- `op`: `pagado` → Pagado · `pendiente` → Pendiente · `anulado` → Cancelado · `cancelado` → Cancelado
- `nc`: `aplicada` → Pagado (verde, "Aplicada") · `aplicada_parcial` → Parcial · `aprobado` → Pendiente · `pendiente_aprobacion` → Borrador (sin aprobar) · `borrador` → Borrador · `cancelada` → Cancelado

#### Scenario: badge para pedido pagado

- GIVEN `<EstadoBadge variant='pedido' estado='pagado_parcial' saldo={0} />`
- WHEN el componente se monta
- THEN renderea badge con `label='Pagado'`, ícono `CheckCircle2`, color verde (`--cf-accent-green`)
- AND el background es `color-mix(in srgb, var(--cf-accent-green) 14%, transparent)`

#### Scenario: badge para NC aplicada

- GIVEN `<EstadoBadge variant='nc' estado='aplicada' />`
- WHEN el componente se monta
- THEN renderea badge con `label='Aplicada'`, color verde
- AND no tiene en cuenta `saldo` (no aplica a variant nc)

#### Scenario: variant no soportada

- GIVEN `<EstadoBadge variant='unknown' estado='X' />`
- WHEN el componente se monta
- THEN se renderea un fallback "Desconocido" con tono gris
- AND NO se lanza error en runtime

### Requirement: EmptyState component

El componente `EmptyState` SHALL renderear un mensaje de "no hay datos" con personalidad: ícono prominent + título + sub-mensaje + opcional CTA.

**Props API**:
- `icon` (ReactNode, required): el ícono a mostrar (típicamente de `lucide-react` con size 28-36).
- `title` (string, required): título del estado vacío.
- `subtitle` (string, optional): mensaje explicativo de qué hacer.
- `cta` (object, optional): `{ label, onClick, variant?: 'primary'|'secondary' }` para acción de CTA.
- `tone` (string): `'default' | 'inline' | 'hero'`. Default `'default'`. `'hero'` usa más padding y dashed border, `'inline'` para casos compactos dentro de tablas.

#### Scenario: empty state de hero card

- GIVEN `<EmptyState icon={<Search size={36}/>} title='Buscá un proveedor' subtitle='...' tone='hero' />`
- WHEN se monta
- THEN se renderea con border dashed, padding `var(--spacing-2xl)`, ícono en círculo de 64x64
- AND el título en `font-lg + font-bold`, subtítulo en `font-sm + text-secondary`

#### Scenario: empty state inline en tabla

- GIVEN `<EmptyState icon={<Coins/>} title='Sin movimientos' tone='inline' />`
- WHEN se monta
- THEN se renderea sin border dashed, padding compacto `var(--spacing-md)`, ícono más chico

#### Scenario: empty state con CTA

- GIVEN `<EmptyState ... cta={{label: 'Crear pedido', onClick: fn, variant: 'primary'}} />`
- WHEN el usuario clickea el botón
- THEN se invoca `onClick`
- AND el botón usa la clase `actionChip` o `btnPrimary` según variant

### Requirement: MetricTile component

El componente `MetricTile` SHALL renderear un valor métrico con label, valor numérico tabular, hint de contexto, y un tone visual (debe / haber / neutral / estimate) que afecta el border-left y opcionalmente el background.

**Props API**:
- `label` (string, required): etiqueta corta uppercase (ej. "Saldo ARS").
- `value` (string|number, required): valor formateado (string) o crudo (se formatea con `toLocaleString` si es número).
- `hint` (string, optional): contexto secundario (ej. "5 movimientos").
- `tone` (string): `'debe' | 'haber' | 'neutral' | 'estimate'`. Default `'neutral'`.
- `icon` (ReactNode, optional): override del ícono default por tone.

#### Scenario: tile de saldo deudor

- GIVEN `<MetricTile label='Saldo ARS' value='$5.000,00' hint='3 movs' tone='debe' />`
- WHEN se monta
- THEN border-left es `var(--cf-accent-red)`, ícono `ArrowDownToLine`
- AND el valor usa `font-mono + tabular-nums + font-2xl + font-bold`

#### Scenario: tile estimate con striped pattern

- GIVEN `<MetricTile label='Consolidado ARS' value='$10.000,00' tone='estimate' />`
- WHEN se monta
- THEN border-left es `var(--cf-accent-orange)`
- AND el background tiene `repeating-linear-gradient` (striped pattern) sutil
- AND el hint usa color `--cf-accent-orange` para indicar "estimado"

### Requirement: LoadingBlock component

El componente `LoadingBlock` SHALL renderear un spinner azul con texto explicativo, usable como bloque centrado o overlay.

**Props API**:
- `text` (string, optional): mensaje. Default `'Cargando…'`.
- `tone` (string): `'block' | 'inline'`. Default `'block'`.

#### Scenario: loading block centrado

- GIVEN `<LoadingBlock text='Cargando pedidos…' />`
- WHEN se monta
- THEN se renderea un `<Loader2 size={28}>` con animación spin, color `--cf-accent-blue`
- AND el texto debajo en `font-sm + text-secondary`

### Requirement: FiltersBar component

El componente `FiltersBar` SHALL ser un contenedor flexible para los filtros del top de cada tab (selects, date pickers, autocomplete, SearchInput) con layout consistente.

**Props API**:
- `children` (ReactNode, required): los filtros a renderear como children.
- `actions` (ReactNode, optional): botones primarios alineados a la derecha (ej. "Nuevo pedido").

#### Scenario: filters con acción primaria

- GIVEN `<FiltersBar actions={<Button>Nuevo pedido</Button>}><Select.../><DatePicker.../></FiltersBar>`
- WHEN se monta
- THEN los filtros se ordenan en flex-wrap con gap `var(--spacing-sm)`
- AND el slot `actions` queda al final con `margin-left: auto`
- AND en mobile (<768px) el slot `actions` baja a una nueva línea

### Requirement: Componentes shared deben tener JSDoc completo

Cada componente shared SHALL tener un comentario JSDoc al inicio con: descripción del componente, ejemplo de uso, todas las props documentadas con tipo y descripción.

#### Scenario: JSDoc presente en cada shared

- GIVEN cualquier componente en `frontend/src/components/compras/_shared/*.jsx`
- WHEN se inspecciona el código
- THEN tiene un bloque `/** ... */` antes de la declaración del componente
- AND lista cada prop con su tipo y propósito
- AND incluye al menos un ejemplo de uso

### Requirement: Componentes shared NO deben tener dependencias circulares

Los componentes en `_shared/` SHALL NO importar otros componentes del módulo compras (Tab*, Modal*, Panel*) para evitar dependencias circulares.

#### Scenario: import legal

- GIVEN un archivo en `_shared/`
- WHEN se inspeccionan sus imports
- THEN solo importa de: React, lucide-react, otros archivos de `_shared/`, `frontend/src/services/api.js`, `frontend/src/contexts/*`, `frontend/src/components/SearchInput.jsx`, design tokens (CSS)
- AND NO importa de: archivos `Tab*`, `Modal*`, `Panel*` del módulo compras

#### Scenario: detección de import ilegal

- GIVEN un archivo `_shared/X.jsx` con `import Y from '../TabPedidosCompra'`
- WHEN se ejecuta ESLint
- THEN ESLint marca el import como warning/error por dependencia circular potencial (regla `import/no-cycle`)
