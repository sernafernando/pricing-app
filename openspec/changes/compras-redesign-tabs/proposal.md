# Proposal: Rediseño visual del módulo Compras

**Change ID**: `compras-redesign-tabs`
**Status**: proposed
**Mode**: hybrid (openspec + engram)

## Intent

El módulo compras tiene 8 componentes principales (tabs + paneles) y 11 modales que comparten estructura subyacente uniforme (todos `<table>` + filtros + estados) pero **divergen en estética visual** porque cada uno mantiene su propio CSS module heredado de iteraciones previas. Solo `TabCCProveedores` fue rediseñado con la dirección visual "Editorial Finance Terminal" (PRs #618 + #619 mergeados sin cambios visuales pedidos por el user).

**El problema**: la inconsistencia visual entre tabs degrada la percepción del módulo y exige al usuario re-aprender patrones (ej. "¿este pedido está pagado?" se responde distinto en CC que en Pedidos). Hay deuda visual concreta: badges sin variantes de estado, empty states genéricos ("No hay registros"), botones primarios saturados con bg sólido, columnas sin tabular-nums (montos desalineados), tablas sin colgroup (columnas se solapan con valores largos).

**El objetivo**: aplicar el lenguaje visual ya validado del CC al resto del módulo, manteniendo 100% de la funcionalidad y los tokens `--cf-*` existentes.

## Scope

### In Scope

**Componentes shared nuevos** (extraídos del CC):
- `frontend/src/components/compras/_shared/DataTable.jsx` + `.module.css` — tabla unificada con colgroup, tabular-nums, alignment correcto, hover con accent lateral, empty/loading slots
- `frontend/src/components/compras/_shared/EstadoBadge.jsx` — con variantes (`pedido`, `op`, `nc`) que mapean estados de cada workflow a tonos visuales (Pagado/Parcial/Pendiente/Cancelado/Borrador y equivalentes)
- `frontend/src/components/compras/_shared/EmptyState.jsx` — ícono + título + sub-mensaje + opcional CTA
- `frontend/src/components/compras/_shared/MetricTile.jsx` — label + value (mono tabular) + hint + tone (debe/haber/neutral/estimate)
- `frontend/src/components/compras/_shared/LoadingBlock.jsx` — spinner azul + texto explicativo
- `frontend/src/components/compras/_shared/FiltersBar.jsx` — toolbar con slots para selects, date pickers, autocomplete, SearchInput

**Tokens nuevos** (en `frontend/src/styles/design-tokens.css`):
- `--cf-shadow-card`, `--cf-shadow-modal` — sombras reusables (hoy hardcoded en CC)
- `--font-mono` formal (stack centralizada para tabular nums)
- `--cf-saldo-positive` / `--cf-saldo-negative` — alias semánticos sobre accent-green/red

**Tabs/paneles rediseñados** (7):
- `TabPedidosCompra` (737 líneas)
- `TabOrdenesPago` (828 líneas)
- `TabNCsLocales` (634 líneas)
- `TabSaleDocumentCatalog` (194 líneas)
- `TabPapelera` (288 líneas)
- `TabReconciliacion` (320 líneas) — usa MetricTile para sus 4 métricas
- `PanelImputaciones` (366 líneas) — coherente entre uso inline (CC) y standalone

**Modales rediseñados** (11):
- ModalPedidoDetalle, ModalPedidoCompra, ModalCorregirPedido
- ModalOrdenPagoDetalle, ModalOrdenPagoNueva, ModalEjecutarPago
- ModalNCLocalDetalle, ModalNCLocal, ModalAplicarNC, ModalVincularFacturaNC
- ModalConfirmarEliminacion, ModalVincularFactura

**Refactor de CC**:
- `TabCCProveedores` consume los nuevos shared components (DataTable, MetricTile, EstadoBadge, etc.) — cero cambio visual visible.

### Out of Scope

- **Cambios funcionales**: handlers, hooks, modales (lógica), permisos, formatters de moneda/fecha — todo se preserva intacto.
- **Cambios de backend / API**: el rediseño es 100% frontend.
- **Migración a TypeScript**: mantenemos JSX, no migramos.
- **Tests E2E nuevos**: el módulo no tiene E2E hoy; agregarlo es proyecto aparte.
- **Otros módulos** (RMA, Productos, Caja, ML, Permisos): este change toca SOLO `frontend/src/components/compras/` + `frontend/src/styles/design-tokens.css`.
- **Refactor de PanelImputaciones para que sea un sub-componente de DataTable**: lo dejamos standalone con coherencia visual; arquitectura aparte.

## Approach

**Fragmentación en 6 PRs sub-secuenciales** (decisión usuario: shared upfront por eficiencia):

| # | PR | Contenido | Visible al user |
|---|---|---|---|
| 0 | tokens | 4 tokens nuevos en design-tokens.css | invisible |
| 1 | shared | 6 componentes shared extraídos del CC + refactor de CC para consumirlos | invisible (cero cambio visual en CC) |
| 2 | pedidos | TabPedidosCompra + 3 modales | sí |
| 3 | ops | TabOrdenesPago + 3 modales | sí |
| 4 | ncs | TabNCsLocales + 4 modales | sí |
| 5 | admin | TabReconciliacion + SaleDoc + Papelera + Imputaciones + 2 modales | sí |

**Por qué shared upfront** (Opción 3 modificada vs Opción 2 inicial):
- El patrón ya está validado en CC (PRs #618 + #619 mergeados sin pedidos de cambio).
- 4 tabs van a usar 80%+ las mismas piezas → extraer ahora elimina duplicación.
- Bug fix futuro en 1 lugar afecta a todos los tabs.
- Refactor del CC para consumir shared es trivial (su CSS y JSX pasan a shared casi 1:1).

**Estética**: Editorial Finance Terminal (ya documentada en commit `caa26949` del CC):
- Tipografía: distinct headers en uppercase 10-12px tracking 0.06-0.08em, títulos -0.01em letter-spacing, números con `font-mono` + `tabular-nums`
- Color: tokens `--cf-*` existentes; debe en rojo, haber en verde, saldo bold; `color-mix()` para tints; chips sutiles en lugar de bg sólido
- Layout: hero card con identidad + metrics tiles, quick actions como chips, tabla con colgroup, cards colapsables `<details>/<summary>`, empty states con personalidad
- Motion: transitions 150-200ms ease-out, hovers sutiles, chevron rotación al expandir, accent lateral animado en filas navegables

## Affected Areas

| Área | Impact | Description |
|---|---|---|
| `frontend/src/styles/design-tokens.css` | Modified | +4 tokens (shadow-card, shadow-modal, font-mono, saldo-pos/neg) |
| `frontend/src/components/compras/_shared/` | New | 6 componentes shared (DataTable, EstadoBadge, EmptyState, MetricTile, LoadingBlock, FiltersBar) |
| `frontend/src/components/compras/TabCCProveedores.jsx` | Modified | Refactor para consumir shared; cero cambio visual |
| `frontend/src/components/compras/TabCCProveedores.module.css` | Modified | Remoción de clases que se mueven a shared |
| `frontend/src/components/compras/TabPedidosCompra.{jsx,module.css}` | Modified | Rediseño completo con shared |
| `frontend/src/components/compras/TabOrdenesPago.{jsx,module.css}` | Modified | Rediseño completo con shared |
| `frontend/src/components/compras/TabNCsLocales.{jsx,module.css}` | Modified | Rediseño completo con shared + variant `nc` en EstadoBadge |
| `frontend/src/components/compras/TabSaleDocumentCatalog.{jsx,module.css}` | Modified | Rediseño completo |
| `frontend/src/components/compras/TabPapelera.{jsx,module.css}` | Modified | Rediseño completo |
| `frontend/src/components/compras/TabReconciliacion.{jsx,module.css}` | Modified | Rediseño + uso de MetricTile en métricas |
| `frontend/src/components/compras/PanelImputaciones.{jsx,module.css}` | Modified | Rediseño coherente con uso inline en CC |
| `frontend/src/components/compras/Modal*.{jsx,module.css}` | Modified | 11 modales rediseñados (junto con su tab) |

**Total estimado**: ~9.500 líneas JSX/CSS tocadas, ~1.500 líneas de shared nuevas.

## Risks

| Riesgo | Likelihood | Mitigation |
|---|---|---|
| Densidad info en TabPedidos/TabOPs no entra a 1280px con padding del CC | Med | Colgroup específico por tab (no copiar widths del CC ciegamente); responsive `min-width` con scroll-x |
| Workflow de NCs tiene estados más granulares que pedidos | High | Variante `nc` en EstadoBadge mapea: `borrador → pendiente_aprobacion → aprobado → aplicada_parcial → aplicada → cancelada` |
| Modales grandes (NCDetalle 726, PedidoDetalle 543) — riesgo de romper Timeline / payload colapsable / acciones | High | Testing visual manual obligatorio por modal antes de mergear; preservar jerarquía de `<details>` existente |
| PanelImputaciones tiene doble uso (inline en CC + standalone) | Med | Tratar como un solo componente; verificar ambos contextos en el PR de admin |
| Inconsistencia entre PRs si los criterios derivan | Med | Cada PR consume los mismos shared del PR1 → inconsistencia imposible por construcción |
| Bug en shared se propaga a todos los tabs | Low | Cada shared se valida en el refactor del CC (PR1) antes de aplicarse en otros tabs |
| Tokens nuevos chocan con existentes en otros módulos | Low | Los tokens nuevos son aditivos; no modifican nombres existentes |
| ESLint / build break por imports circulares en shared | Low | Shared sin dependencias entre sí; CSS Modules autocontenidos |

## Rollback Plan

Cada PR es **independiente y revertible** vía `git revert`:

- **PR0 (tokens)**: revert revierte los 4 tokens nuevos. Como son aditivos, ningún consumer existente se rompe (los componentes que los consumen vienen en PRs siguientes).
- **PR1 (shared)**: revert revierte la creación de `_shared/` + el refactor del CC. CC vuelve a su estado pre-shared (commit `dce8715a`). Para revertir limpio, primero hay que revertir PRs que consumen shared (si ya estuvieran mergeados).
- **PR2-5 (tabs)**: revert revierte el rediseño de ese tab y sus modales. Los demás tabs siguen funcionando porque consumen shared (que sigue ahí).

**Orden de rollback** si hay que revertir todo: PR5 → PR4 → PR3 → PR2 → PR1 → PR0 (último en mergear, primero en revertir).

**Cláusula de salida temprana**: si después de PR2 (pedidos) el user no convence con la estética aplicada en otro contexto (lista plana vs cards), pausar. PRs 3-5 quedan en standby hasta resolver. PR1 (shared) y PR2 (pedidos) ya mergeados se pueden revertir o iterar.

## Dependencies

- Ninguna externa.
- **Pre-requisito interno**: PR0 (tokens) debe mergearse antes de PR1.
- **Cadena**: PR1 (shared) debe mergearse antes de PRs 2-5. PRs 2-5 son independientes entre sí (pueden mergearse en cualquier orden post-PR1, aunque la propuesta es secuencial pedidos → ops → ncs → admin para validar el patrón en complejidad creciente).

## Success Criteria

- [ ] Los 4 tokens nuevos están definidos en `design-tokens.css` y consumidos por al menos 1 componente
- [ ] Existe `frontend/src/components/compras/_shared/` con los 6 componentes documentados (cada uno con JSX + CSS Module + JSDoc de props)
- [ ] `TabCCProveedores` consume los shared sin cambio visual (capturable comparando screenshots antes/después del PR1)
- [ ] Los 7 tabs/paneles rediseñados pasan ESLint clean
- [ ] Los 11 modales rediseñados pasan ESLint clean
- [ ] Visualmente, los 8 componentes (CC + 7 nuevos) son **indistinguibles entre sí en lenguaje visual** (badges con misma escala/tipografía, tablas con mismas columnas/spacing, empty states con misma estructura)
- [ ] El usuario aprueba al menos 1 tab del módulo en producción sin pedir revert
- [ ] Cero regresión funcional reportada en los 30 días siguientes a cada PR mergeado
- [ ] El módulo build (`npm run build`) sin errores ni warnings nuevos
- [ ] Modo claro y oscuro verificados en cada tab + modal

## Notas

- **Estética de referencia**: ver commit `caa26949 feat(compras/cc): rediseño visual — Editorial Finance Terminal` y commit `ac606da2 feat(compras/cc): vistas unificadas + spoiler por pedido + impts inline` para el patrón completo aplicado en CC.
- **Tokens validados**: el user explícitamente aprobó los 4 tokens nuevos antes de proceder.
- **No hay tests E2E** en pricing-app frontend; la validación es visual + ESLint + build. Tests futuros son scope aparte.
