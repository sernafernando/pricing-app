# Apply Progress: feat-compras-pedidos-layout-y-alerta-factura

**Change**: feat-compras-pedidos-layout-y-alerta-factura
**Mode**: Standard (strict_tdd not enabled; no openspec/config.yaml tdd flag)
**Branch**: `feat/compras-pedidos-layout-y-alerta-factura`
**Delivery**: single-pr → `main` (Low risk, Decision needed: No). Stacked on #1347. Do not merge #1347. Do not open PR from apply.
**Work unit**: `apply-layout-and-alerta-docs`

## Completed Tasks

- [x] 1.1 Empresa cell class + full `empresa_nombre`. Measured cap: `104px` (Pastoriza / wrapped Grupo Gauss + 2×16px td pad). Locked cols unchanged: Fecha pago `110`, Mon `60`, Estado `152`, Proceso `220`, Proveedor no width.
- [x] 1.2 `.empresaCell` 2-line centered, `text-overflow: clip` (no ellipsis).
- [x] 1.3 `.rowActions` 2-column CSS grid; `COLUMNS.acciones` `104px` (< 180).
- [x] 2.1 Unit: keep 110/152/220; Acciones `<col>` `< 180px`; no literal Empresa px.
- [x] 2.2 Visual host `1360px` (1280–1400, not 1600). Fixtures Grupo Gauss + Pastoriza full text; Acciones 2-col geometry; Proveedor/Mon overlap 0.
- [x] 3.1 RUNBOOKS §7: cron required; `python -m app.scripts.dispatch_factura_cargada_alerts`; 5m delay; empty `numero` no-op.
- [x] 3.2 Post-deploy checklist: crontab every minute.
- [x] 3.3 Guía + novedad: ADMIN role is not enough; recipients = `administracion.ver_alertas_factura`; Chicho assigns.
- [x] 3.4 **Skipped Python** — no wiring gap (see Issues).

## Work Unit Evidence

### Unit 1 — apply-layout-and-alerta-docs

| Evidence | Value |
|---|---|
| Focused test command and exact result | `cd frontend && pnpm exec vitest run src/components/compras/TabPedidosCompra.test.jsx` → **16 passed** (1 file). ESLint on changed JS/JSX: EXIT 0. |
| Runtime harness command/scenario and exact result | `cd frontend && pnpm exec vitest run --project=visual src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` → **1 passed** (Chromium). Host 1360px; Grupo Gauss + Pastoriza full/no ellipsis; Acciones two unique X columns; Proveedor/Mon overlap area 0. |
| Rollback boundary | Revert `TabPedidosCompra.jsx` / `.module.css` / unit + visual tests, and the RUNBOOKS / post-deploy / guía / novedad hunks. No Python files. DataTable untouched. |

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modified | Empresa wrapper; empresa `104px`; acciones `104px`; `data-testid`s |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modified | `.empresaCell` 2-line center; `.rowActions` 2-col grid |
| `frontend/src/components/compras/TabPedidosCompra.test.jsx` | Modified | Acciones `<col>` `< 180px` |
| `frontend/src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` | Modified | 1360 host; Empresa fixtures; Acciones geometry; overlap 0 |
| `docs/RUNBOOKS.md` | Modified | §7 factura-cargada cron |
| `docs/modulos/compras-post-deploy-checklist.md` | Modified | Crontab every-minute checkbox |
| `docs/modulos/compras-guia-usuario.md` | Modified | ADMIN-alone insufficient + cron |
| `frontend/src/novedades/2026-09-23-compras-pipeline-ux.md` | Modified | Same ADMIN/cron sentence |
| `openspec/changes/feat-compras-pedidos-layout-y-alerta-factura/tasks.md` | Modified | All 9 tasks `[x]` |

## Deviations from Design

None — implementation matches design. Empresa exact px is an apply measurement (`104px`, inside the ~88–120 expected band). Visual host is 1360 (inside 1280–1400). Python untouched.

## Issues Found

Task 3.4 skipped: sweep is already wired. `dispatch_factura_cargada_alerts.py` calls `disparar_alertas_factura_pendientes`. `notificar_factura_cargada` returns `[]` when `numero` is empty/whitespace. Check path only sets `alerta_pendiente_hasta`; no in-process notify. No production Python change.

## Workload / PR Boundary

- Mode: single PR (not opened in apply)
- Current work unit: apply-layout-and-alerta-docs
- Boundary: planning commit `9aa673ba` → this apply (layout + alert docs)
- Estimated review budget impact: Low (under 400 authored lines)

## Status

9/9 tasks complete. Ready for verify.
