# Design: Shrink Pedidos Fecha pago column

## Technical Approach

One-liner: set `COLUMNS.fecha_pago.width` from `160px` to `110px`; keep `.fechaPagoCell` wrap so the urgency badge stacks under `dd/mm/yyyy`.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|----------|---------|----------|--------|
| Width | 100 vs 110 vs 120 | 100 clips header/date (16px td/th pad + nowrap `FECHA PAGO`); 120 wastes Gabe range | **`110px`** |
| Badge | Keep wrap vs inline | Inline needs ~160px again | **Keep wrap** |
| CSS | None vs badge `margin-left: 0` | Badge has gap + `margin-left`; wrap indents | **Optional `margin-left: 0`** |
| DataTable | Per-col padding vs untouched | Shared API out of scope | **Untouched** |
| Test | Skip vs `<col>` style vs Playwright | jsdom `css: false`; visual suite is chip-only | **Cheap `<col>` assert** |

## Data Flow

```
COLUMNS.fecha_pago.width = 110px
        │
        ▼
DataTable <col style={{ width }}>   (unchanged)
        │
        ▼
fecha_pago cell: formatDate + optional badge
        │
        └── .fechaPagoCell flex-wrap → badge MAY go under date
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modify | `fecha_pago` width `160px` → `110px` |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modify (optional) | `.badgeVenceUrgente` / `.badgeVencido` `margin-left: 0` |
| `frontend/src/components/compras/TabPedidosCompra.test.jsx` | Modify | Assert Fecha pago / Estado / Proceso col widths |

Unchanged: DataTable, estado/proceso/moneda widths, backend, visual chip tests.

## Interfaces / Contracts

```js
{ key: 'fecha_pago', label: 'Fecha pago', width: '110px' }
```

Estado `152px`, Proceso `220px`, Mon. `60px`, Proveedor no width.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Fecha pago col `110px`; Estado `152px`; Proceso `220px` | `TabPedidosCompra.test.jsx` — `columnheader` → sibling index → `<col>.style.width` |
| Visual | Painted Proveedor/Mon. overlap | Playwright `tabPedidosCompraFechaPago.visual.test.jsx` (Phase 3 remediates failed verify; jsdom cannot prove geometry) |
| E2E | N/A | Layout-only |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration required. PR to **main** from `feat/compras-pedidos-fecha-pago-col-width`.

## Open Questions

- None
