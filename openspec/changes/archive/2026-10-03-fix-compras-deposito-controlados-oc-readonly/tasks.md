# Tasks: Controlados OC read-only exhibit

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 80–160 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Delivery strategy | ask-on-risk |

### Suggested Work Units

| Unit | Goal | Focused test |
|------|------|--------------|
| 1 | Controlados exhibit + hide control chrome | `pnpm exec vitest run src/components/compras/TabRecepcionDeposito.test.jsx` |

**Apply git:** branch `fix/compras-deposito-controlados-oc-readonly` from **main**, PR to `sernafernando/pricing-app` **main**.

## Phase 1: UI

- [x] 1.1 In `AccordionBodyConOc`, when `pedido.estado === 'controlado'`, render blocks from `lineasErp` (all saldos lines) in a read-only table (no checkbox / tanda).
- [x] 1.2 When controlado, hide faltantes form, responsable picker, `ControlEvidenceFields`, and the control action bar.
- [x] 1.3 Leave `recibido` / `con_faltantes` on the existing `saldo_pendiente !== 0` filter and editable control UI.

## Phase 2: Tests

- [x] 2.1 Controlados + all saldo 0 → item names visible.
- [x] 2.2 Controlados → no Marcar / tanda controls.
- [x] 2.3 Keep / re-run the existing “hides faltantes lines with saldo_pendiente 0” coverage for recibido.

## Phase 3: Docs (if section exists)

- [x] 3.1 Note in `docs/modulos/compras-guia-usuario.md` that Controlados shows OC lines read-only.
