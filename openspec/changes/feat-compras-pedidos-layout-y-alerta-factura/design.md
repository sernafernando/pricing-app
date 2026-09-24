# Design: Pedidos layout + factura-cargada alert ops

## Technical Approach

Two local slices, one PR stacked on #1347.

**Layout:** cell CSS + `COLUMNS` on `TabPedidosCompra` only. Do not change DataTable padding/API.

**Alerts:** document the existing cron. Touch Python only if apply proves sweep/empty-nº is broken (today it is not).

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|----------|---------|----------|--------|
| Empresa wrap | 1-line ellipsis vs 2-line no-ellipsis | Ellipsis hides Grupo Gauss; 2-line shrinks width | **2-line, `text-align: center`, no ellipsis** |
| Empresa width | Keep 140 vs cap to names | 140 wastes; cap = max(Pastoriza, wrapped Grupo Gauss) + 2×16px td pad | **Measure at apply; expected ~88–120px** |
| Acciones | Flex row vs 2-col grid | Row needs ~180px | **`.rowActions { display:grid; grid-template-columns: repeat(2, min-content); }`**; width ~88–110px |
| Locked cols | Cut Estado/Proceso vs keep | User: cut only if design proves | **Keep 110 / 60 / 152 / 220** |
| Flexible | Cap Proveedor vs keep flex | Only leftover absorber | **Proveedor uncapped** |
| Tests | More `<col>` px vs geometry | Chicho: brittle px | **Keep Fecha pago `110px` `<col>`; Playwright geometry at 1280–1400 (drop 1600 wrapper)** |
| DataTable | Shared nowrap/pad vs cell CSS | Shared API out of scope | **Cell CSS only** |
| Cron | New health vs docs | Other Compras crons are docs-only; script already wired | **RUNBOOKS + post-deploy + guía; no health endpoint** |
| Recipients spec | Re-MODIFY UNION vs ADD ops | Other change already deltas recipients | **ADD cron/ops only** |
| Empty nº | New UI vs keep no-op | Persist requires numero; no-op already | **Keep no-op; no UX unless apply finds a check-without-numero path** |

## Data Flow

```
Pedidos COLUMNS (capped except Proveedor)
  Empresa cell ── wrap 2 lines, center, no ellipsis
  Acciones     ── 2-col grid (extra icons add rows)
  Proveedor    ── flex leftover at 1280–1400
        │
        ▼
DataTable <colgroup> (unchanged API)

Check cargada ── alerta_pendiente_hasta = now+5m
        │
        ▼  (no in-process sleep)
crontab * * * * *  python -m app.scripts.dispatch_factura_cargada_alerts
        │
        ▼
disparar_alertas_factura_pendientes
        │  empty numero → notify []
        ▼
resolver(administracion.ver_alertas_factura)  // ADMIN role alone = out
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modify | Empresa wrapper class; Acciones already uses `.rowActions`; set Empresa/Acciones widths |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modify | `.empresaCell` 2-line center; `.rowActions` 2-col grid |
| `frontend/src/components/compras/TabPedidosCompra.test.jsx` | Modify | Keep 110/152/220; Acciones `< 180px`; no new Empresa px |
| `frontend/src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` | Modify | Viewport 1280–1400; Empresa full names; Acciones 2-col; Proveedor/Mon overlap 0 |
| `docs/RUNBOOKS.md` | Modify | New short factura-cargada cron section |
| `docs/modulos/compras-post-deploy-checklist.md` | Modify | Cron checkbox |
| `docs/modulos/compras-guia-usuario.md` | Modify | ADMIN-alone + cron one-liners |
| `frontend/src/novedades/2026-09-23-compras-pipeline-ux.md` | Modify (optional) | Same ADMIN/cron sentence |

Python / Alembic: **none** unless apply finds a proven gap.

## Interfaces / Contracts

```js
{ key: 'fecha_pago', width: '110px' } // locked
{ key: 'moneda', width: '60px' }
{ key: 'estado', width: '152px' }
{ key: 'proceso', width: '220px' }
{ key: 'empresa', width: /* measured cap */ }
{ key: 'acciones', width: /* ~2 icon cols */ }
{ key: 'proveedor' } // no width
```

Visual fixtures MUST include `empresa_nombre: 'Grupo Gauss'` and `'Pastoriza'`.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Fecha pago 110; Estado 152; Proceso 220; Acciones col `< 180px` | jsdom `<col>` style |
| Visual | Full Empresa names, 2-col Acciones, Proveedor/Mon overlap 0 | Playwright at **1280–1400**, not 1600 |
| Docs | Cron command + ADMIN caveat present | Grep in verify |
| Backend | Existing sweep/empty-nº tests | Re-run only if Python changes |

## Threat Matrix

N/A — no new routing, shell, subprocess, VCS/PR, or process-integration boundary. Cron script already exists; this change documents it.

## Migration / Rollout

No schema. PR to **main** from `feat/compras-pedidos-layout-y-alerta-factura` stacked on #1347. Do not merge #1347. Operator must add crontab on deploy (docs). Chicho assigns `administracion.ver_alertas_factura`.

## Open Questions

- None — Empresa exact px is an apply measurement, not a product lock.
