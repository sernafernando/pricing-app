# Compras Visual Coherence

## Purpose

Define el contrato visual cross-component del módulo compras post-rediseño. Garantiza que los 8 componentes (CC + 7 tabs/paneles) y sus 11 modales sean **indistinguibles entre sí en lenguaje visual**: misma escala tipográfica de badges, misma estructura de tablas, misma jerarquía de empty states, misma microinteracción de hover.

Esto es el "acceptance criteria" cross-component que valida que el módulo se sienta como una aplicación coherente, no una colección de pantallas heredadas de iteraciones distintas.

## Requirements

### Requirement: Coherencia de tablas

Todas las tablas del módulo compras SHALL usar el componente `<DataTable />` shared.

Las tablas MUST tener:
- Headers con `font-size: 10px`, `text-transform: uppercase`, `letter-spacing: 0.08em`, color `--cf-text-tertiary`
- Cells con `font-size: var(--font-sm)`, `vertical-align: middle`
- Numéricas con `font-family: var(--font-mono)` y `font-variant-numeric: tabular-nums`
- Anchos de columna fijos via `<colgroup>`
- `min-width: 720px` con scroll-x cuando overflow
- Hover en row: background `var(--cf-bg-hover)` + accent lateral animado `scaleY` cuando navegable

#### Scenario: comparación visual entre tabs

- GIVEN un usuario en `TabPedidosCompra` y luego en `TabOrdenesPago`
- WHEN compara las tablas en ambos tabs
- THEN los headers tienen la misma altura, peso tipográfico, color, padding
- AND las celdas numéricas (montos) tienen el mismo alignment, font, color tonal (debe rojo, haber verde, saldo bold)
- AND el hover sobre una row se ve idéntico (background y accent lateral)

### Requirement: Coherencia de badges de estado

Todos los badges de estado del módulo compras SHALL usar el componente `<EstadoBadge />` shared con la variante apropiada (`pedido`, `op`, `nc`).

Los badges MUST tener:
- `font-size: 10px`, `text-transform: uppercase`, `letter-spacing: 0.06em`, `font-weight: 700`
- `padding: 2px 8px 2px 6px`
- `border-radius: var(--radius-full)`
- Ícono lucide al inicio (size 11)
- 5 tonos consistentes: verde (Pagado/Aplicada), amarillo (Parcial), naranja (Pendiente), gris (Cancelado), gris suave (Borrador)

#### Scenario: badge entre 3 contextos

- GIVEN un pedido pagado en `TabPedidosCompra`, una OP pagada en `TabOrdenesPago`, una NC aplicada en `TabNCsLocales`
- WHEN el usuario los ve uno al lado del otro
- THEN los 3 badges tienen el mismo tamaño, peso, padding, ícono check
- AND los 3 son verdes (`--cf-accent-green`)
- AND solo difiere el label: "Pagado" / "Pagado" / "Aplicada"

### Requirement: Coherencia de empty states

Todos los empty states del módulo SHALL usar el componente `<EmptyState />` shared con tone apropiado (`hero` para containers grandes, `inline` para dentro de tablas).

Los empty states MUST tener:
- Ícono prominent (size 28-36 según tone)
- Título en `font-lg + font-bold` (hero) o `font-sm + font-medium` (inline)
- Sub-mensaje opcional en `font-sm + text-secondary`
- Para `tone='hero'`: `border: 1px dashed var(--cf-border-default)` + `border-radius: var(--radius-xl)` + padding `var(--spacing-2xl)`

#### Scenario: empty state al cargar tab sin proveedor

- GIVEN el usuario abre un tab sin tener proveedor seleccionado (donde aplique)
- WHEN el componente se monta
- THEN se ve un EmptyState con ícono Search/Inbox, título "Buscá un proveedor" o equivalente, sub-mensaje explicativo
- AND el estilo es idéntico entre `TabCCProveedores`, `TabPedidosCompra`, etc.

#### Scenario: empty state dentro de tabla

- GIVEN una tabla con `rows=[]` y filtros aplicados que no devuelven datos
- WHEN se renderea
- THEN dentro del `<tbody>` aparece un único `<tr>` con un `<EmptyState tone='inline'>`
- AND el padding/altura es consistente entre tabs

### Requirement: Coherencia de quick actions

Las acciones rápidas (creación, operaciones) SHALL renderearse como **chips sutiles** con `border-radius: var(--radius-full)`, NOT como botones primarios saturados con `bg` de color sólido.

Los chips MUST tener:
- `padding: 6px 12px`
- `border: 1px solid var(--cf-border-default)`
- `background: transparent` (default), `color-mix(... 8%)` para variants accent/danger
- `font-size: var(--font-xs)`, `font-weight: 600`, `letter-spacing: 0.01em`
- Hover: border-color blue + background tint
- Variants: `actionChip` (default), `actionChipAccent` (verde), `actionChipDanger` (rojo)

#### Scenario: barra de acciones en CC y Pedidos

- GIVEN el usuario está en `TabCCProveedores` con un proveedor activo
- AND el usuario navega a `TabPedidosCompra`
- THEN los chips de "Nuevo pedido", "Nueva OP", etc. se ven idénticos en ambos tabs
- AND ningún botón primario del módulo es un rectángulo azul sólido (excepto en submit de modales donde es esperable)

### Requirement: Coherencia de cards colapsables

Cuando un componente del módulo necesita una card colapsable (`<details>/<summary>`), SHALL usar el patrón aplicado en `TabCCProveedores` `GrupoPedidoCard`:

- Card con `border` que cambia a `border-color: --cf-accent-blue` cuando `[open]`
- Summary con chevron rotado 90° al abrir
- Body con padding consistente

#### Scenario: drill-down en por-pedido y en lista de OPs detalladas

- GIVEN el usuario expande un pedido en `TabCCProveedores` (vista por-pedido)
- AND luego expande una OP que tiene desglose en `TabOrdenesPago`
- THEN ambos componentes tienen la misma transición del chevron, mismo border azul al abrir, mismo padding del body

### Requirement: Coherencia de modales

Todos los modales del módulo SHALL tener:
- `backdrop-filter: blur(2px)` en el overlay
- `border-radius: var(--radius-xl)` en el contenido
- `box-shadow: var(--cf-shadow-modal)`
- Header con título en `font-lg + font-bold` y botón close `<X size={18}/>`
- Help banner (cuando aplique) con `border-left: 3px solid var(--cf-accent-blue)`
- Form labels en uppercase tracking 0.06em
- Botones de submit con `filter: brightness(1.08)` en hover

#### Scenario: modal de detalle entre pedido y OP

- GIVEN el usuario abre `ModalPedidoDetalle` y luego `ModalOrdenPagoDetalle`
- WHEN compara las cabeceras
- THEN tienen el mismo padding, mismo tipografía del título, mismo close button
- AND ambos overlays tienen el mismo blur

### Requirement: Funcionalidad preservada al 100%

El rediseño SHALL preservar 100% de la funcionalidad existente. Esto incluye:
- Handlers, hooks, modales (lógica), permisos, formatters de moneda/fecha
- Endpoints consumidos
- Estados internos
- Navegación drill-down
- Comportamiento de filtros, paginación, búsqueda

NINGUNA funcionalidad SHALL ser modificada o removida como parte de este change.

#### Scenario: regresión cero post-merge

- GIVEN el módulo compras antes del rediseño (pre-PR0) funciona en producción
- WHEN se mergean los 6 PRs (tokens + shared + 4 tabs)
- THEN cada flujo de usuario (crear pedido, aprobar, pagar, anular, etc.) funciona idéntico
- AND ninguna acción produce un error nuevo
- AND ningún campo desaparece de la UI
- AND ningún permiso deja de respetarse

### Requirement: ESLint y build limpios

El código resultante SHALL pasar ESLint (`npx eslint src/components/compras/`) sin errores ni warnings nuevos, y `npm run build` SHALL completar sin errores.

#### Scenario: CI quality gates

- GIVEN el código del rediseño en cada PR
- WHEN se corre `npx eslint frontend/src/components/compras/`
- THEN sale con código 0 (cero errores, cero warnings nuevos)
- AND `npm run build` también sale con código 0

### Requirement: Modo claro y oscuro funcionales

Todos los componentes rediseñados SHALL renderear correctamente en ambos themes (`:root` default oscuro, `:root[data-theme="light"]` claro).

#### Scenario: switch de tema

- GIVEN el usuario está en cualquier tab del módulo en modo oscuro
- WHEN cambia a modo claro vía ThemeContext
- THEN todos los textos siguen legibles (contraste adecuado)
- AND los borders/sombras se adaptan al theme
- AND no hay elementos invisibles ni colores hardcodeados que rompan la legibilidad
