# Batch D — Migración de botones módulo compras a Tesla outline-subtle

## Status
completed

## Intent
Alinear visualmente todos los botones del módulo compras al sistema Tesla `outline-subtle-*` que usa el resto del proyecto. El usuario reportó que el botón "Aplicar" en `PanelImputaciones` era azul sólido y rompía la consistencia del look & feel.

## Scope
CSS Modules exclusivamente. **NO se modifica ningún `.jsx`**. La interfaz externa (names de clases CSS) se preserva 1:1 — solo cambia la definición interna usando `composes` desde `buttons-tesla.css`.

## Changes by file

| Archivo | Cambios |
|---|---|
| `PanelImputaciones.module.css` | Migración completa: `.btnPrimary`, `.btnGhost`, `.btnDanger`, `.btnAction`, `.refreshBtn` pasaron de custom CF a Tesla subtle. Se eliminó el grupo base compartido (Tesla ya lo provee). |
| `TabPedidosCompra.module.css` | `.btnSecondary`, `.iconBtn` pasaron de `secondary` (sólido) a `outline-subtle-primary`. `.pageBtn` pasó a `outline-subtle-primary icon-only xs`. |
| `TabOrdenesPago.module.css` | Idem TabPedidosCompra. |
| `TabReconciliacion.module.css` | `.btnPrimary` → `outline-subtle-warning` (acción admin sensible, regla D.2). `.btnSecondary` → `outline-subtle-primary`. |
| `TabCCProveedores.module.css` | Bonus D.4: eliminé `.btnPrimary` que era código muerto (definido pero no referenciado en JSX). |
| `ModalOrdenPagoNueva.module.css` | `.bannerDismiss` ("Entendido") → `ghost` (no protagonista, regla D.2). `.btnSecondary` → `outline-subtle-primary`. |
| `ModalEjecutarPago.module.css` | `.btnSecondary` → `outline-subtle-primary`. |
| `ModalPedidoCompra.module.css` | `.btnSecondary` → `outline-subtle-primary`. |
| `ModalPedidoDetalle.module.css` | `.btnSecondary` → `outline-subtle-primary`. |

Total: **9 archivos CSS modificados, 0 JSX tocados.**

## Button count migrated
- 15 clases CSS de botón tocadas
- Cobertura: 100% del módulo compras usando variantes `outline-subtle-*` o `ghost` (cero `secondary` sólido, cero variantes "árbol de navidad" como `primary`/`danger`/`success` directos)

## Mapeo aplicado

| Clase compras | Tesla composes | Razón |
|---|---|---|
| `.btnPrimary` (neutral) | `outline-subtle-primary sm` | Acción principal neutra (Aplicar, Guardar) |
| `.btnPrimary` (TabReconciliacion) | `outline-subtle-warning sm` | Forzar recon = acción admin sensible |
| `.btnSuccess` | `outline-subtle-success sm` | Ya estaba (sin cambio en 5 archivos) |
| `.btnDanger` | `outline-subtle-danger sm` | Ya estaba / migrado en PanelImputaciones |
| `.btnWarning` | `outline-subtle-warning sm` | Ya estaba (ModalOrdenPagoNueva) |
| `.btnGhost` | `ghost sm` | Cancelar, paginador |
| `.btnSecondary` | `outline-subtle-primary sm` | Cancelar / navegar |
| `.btnAction` (sensible) | `outline-subtle-warning xs` | Desimputar inserta reversal |
| `.iconBtn` | `outline-subtle-primary icon-only sm` | Ver/detalle en fila |
| `.iconBtnPrimary/Success/Danger` | `outline-subtle-* icon-only sm` | Ya estaban bien |
| `.pageBtn` | `outline-subtle-primary icon-only xs` | Paginación con chevrons |
| `.refreshBtn` | `outline-subtle-primary sm` | Refrescar data |
| `.bannerDismiss` | `ghost sm` | "Entendido" no protagonista |

## Verification
- `npx eslint src/components/compras/ src/pages/AdministracionCompras.jsx` → limpio (0 errores, 0 warnings).
- Grep `btn-tesla secondary` en módulo compras → 0 matches.
- Grep `btn-tesla (primary|danger|success)\b` (sólidos) en módulo compras → 0 matches.

## Risks
1. **`.modalCloseBtn` NO migrado a `btn-close-tesla`**: La clase Tesla usa `position: absolute; top/right: spacing-md;`. Los modales de compras tienen `.modalHeader` con flex/space-between y el close-btn está en el flow del header (al lado del título). Migrar rompería layout. Queda con su definición CF tokens local que es coherente con el tema. Si en el futuro se quiere unificar, requiere refactor del markup del header, no solo CSS.
2. **`.iconBtn` pasó de fondo sólido gris a transparente heredando color**: cambio visual notable pero intencional — el proyecto (ventas, productos) ya usa este patrón. Los icon-only quedan más discretos y limpios en las filas de tabla.
3. **`.viewBtn`/`.viewBtnActive` en TabCCProveedores**: son toggles de vista ("Cronológico" / "Agrupado por pedido") con estilo pill-group. NO se migraron porque no son botones standalone — son un grupo toggle visualmente integrado. Podrían migrarse a `toggle-active` pero requiere análisis del comportamiento (fuera de scope botones individuales).
4. **`.subTabBtn` en TabOrdenesPago**: son sub-tabs (OPs / Imputaciones), no botones de acción. No tocado.
5. **Bonus**: `TabCCProveedores.module.css` tenía `.btnPrimary` sin uso en JSX — eliminé como cleanup. Si algún dev lo usaba en una rama no mergeada, fallará el build. Low risk (buscado en todo `src/`).

## Contract result
```yaml
status: completed
archivos_modificados:
  - frontend/src/components/compras/PanelImputaciones.module.css
  - frontend/src/components/compras/TabPedidosCompra.module.css
  - frontend/src/components/compras/TabOrdenesPago.module.css
  - frontend/src/components/compras/TabReconciliacion.module.css
  - frontend/src/components/compras/TabCCProveedores.module.css
  - frontend/src/components/compras/ModalOrdenPagoNueva.module.css
  - frontend/src/components/compras/ModalEjecutarPago.module.css
  - frontend/src/components/compras/ModalPedidoCompra.module.css
  - frontend/src/components/compras/ModalPedidoDetalle.module.css
botones_migrados: 15
hallazgos_bonus:
  - "TabCCProveedores: .btnPrimary era código muerto (definido pero no usado en JSX) — eliminado"
  - "PanelImputaciones: .refreshBtn tenía estilos custom full — migrado a outline-subtle-primary sm para consistencia"
  - ".btnAction de PanelImputaciones era naranja custom → warning xs (Tesla) con semántica correcta de acción sensible"
riesgos_documentados:
  - ".modalCloseBtn intencionalmente NO migrado a btn-close-tesla (incompatibilidad de layout)"
  - ".iconBtn cambia de fondo sólido gris a transparente (intencional, alinea con resto del proyecto)"
  - ".viewBtn de TabCCProveedores no tocado (es toggle-group, fuera de scope botones individuales)"
eslint: clean
jsx_modificados: 0
next_recommended: "Commit con mensaje 'fix(compras): alinear botones al sistema Tesla outline-subtle' y abrir PR. Visual regression test recomendado en imputaciones (panel + modal desimputar), reconciliación (modal forzar) y TabPedidos (modal rechazar/cancelar)."
```
