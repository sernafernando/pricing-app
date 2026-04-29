# Design Tokens Finance

## Purpose

Define los 4 tokens CSS nuevos que se agregan a `frontend/src/styles/design-tokens.css` para soportar el rediseño visual del módulo compras. Los tokens son **aditivos** — no modifican ni renombran tokens existentes.

## Requirements

### Requirement: Token --font-mono debe estar formalizado

El sistema SHALL definir el token `--font-mono` como una stack de fuentes monospace centralizada, consumible por cualquier componente que requiera tabular numerals.

La stack MUST incluir, en orden de prioridad:
1. `ui-monospace` (system monospace en macOS)
2. `"SF Mono"` (Safari/macOS)
3. `"JetBrains Mono"` (si el user tiene)
4. `"Cascadia Code"` (Windows)
5. `Menlo`, `Consolas`, `monospace` (fallback)

#### Scenario: consumo del token

- GIVEN un componente que necesita tabular nums (ej. `MetricTile` value)
- WHEN el componente declara `font-family: var(--font-mono)`
- THEN se aplica la stack monospace en el orden definido
- AND ya NO debe haber fallbacks inline `var(--font-mono, ui-monospace, ...)` en el código de los componentes

#### Scenario: token disponible en ambos themes

- GIVEN el sistema en modo claro u oscuro
- WHEN se inspecciona `:root` o `:root[data-theme]`
- THEN `--font-mono` está definido y es el mismo en ambos themes (es una propiedad tipográfica, no de color)

### Requirement: Tokens --cf-shadow-card y --cf-shadow-modal

El sistema SHALL definir 2 tokens de sombra reutilizables:
- `--cf-shadow-card`: sombra sutil para cards y metric tiles (ej. `0 1px 0 rgba(255,255,255,0.05) inset, 0 2px 8px -2px rgba(0,0,0,0.1)`)
- `--cf-shadow-modal`: sombra dramática para overlays modales (ej. `0 20px 60px -20px rgba(0,0,0,0.4)`)

Ambos MUST tener variantes para tema claro y oscuro (en `:root` y `:root[data-theme="light"]`).

#### Scenario: aplicación de shadow-card en MetricTile

- GIVEN un `MetricTile` con `box-shadow: var(--cf-shadow-card)`
- WHEN el componente se renderea en tema oscuro
- THEN la sombra es sutil, oscura, no dramática
- AND en tema claro la sombra es ligera (más basada en alpha sobre fondo claro)

#### Scenario: aplicación de shadow-modal en overlay

- GIVEN el `.modalContent` de un modal con `box-shadow: var(--cf-shadow-modal)`
- WHEN el modal se monta
- THEN la sombra es dramática (offset Y grande, blur grande)
- AND el modal flota visualmente sobre el resto de la UI

### Requirement: Tokens semánticos --cf-saldo-positive y --cf-saldo-negative

El sistema SHALL definir 2 alias semánticos:
- `--cf-saldo-positive`: alias sobre `--cf-accent-green` (saldo a favor / pagado)
- `--cf-saldo-negative`: alias sobre `--cf-accent-red` (deuda / pendiente)

Estos tokens SHOULD usarse en lugar de `--cf-accent-green/red` directamente cuando el contexto sea contable/financiero, para mejorar la legibilidad del código.

#### Scenario: uso semántico en código

- GIVEN una clase `.tdRightSaldoPositive { color: var(--cf-saldo-positive); }`
- WHEN se lee el código
- THEN la intención contable es clara: "saldo a favor"
- AND si en el futuro la convención de color cambia (ej. a azul), se actualiza solo el alias sin tocar consumers

#### Scenario: tokens directos siguen disponibles

- GIVEN componentes existentes que usan `--cf-accent-green` directamente
- WHEN se inspecciona después de la migración
- THEN siguen funcionando porque los alias son aditivos (no reemplazan)
- AND la migración a alias semánticos es opcional, no forzada

### Requirement: Tokens nuevos NO deben romper consumers existentes

Los 4 tokens nuevos MUST ser aditivos. La adición SHALL NO:
- Renombrar tokens existentes
- Cambiar valores de tokens existentes
- Cambiar la cascada de variables CSS

#### Scenario: módulos no-compras siguen funcionando

- GIVEN cualquier módulo fuera de compras (RMA, Productos, Caja, etc.)
- WHEN el commit de tokens nuevos se mergea
- THEN ningún componente en RMA/Productos/Caja se ve diferente
- AND el build (`npm run build`) sigue limpio

#### Scenario: tokens existentes siguen disponibles

- GIVEN cualquier componente que usa `--cf-accent-green`, `--cf-bg-card`, `--spacing-md`, etc.
- WHEN el commit se mergea
- THEN los tokens siguen funcionando exactamente igual
