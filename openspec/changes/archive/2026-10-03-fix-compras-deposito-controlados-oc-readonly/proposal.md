# Proposal: Controlados shows OC content read-only

## Intent

On Depósito → Controlados, a CON-OC pedido MUST show every linked OC line for exhibit. Operators MUST NOT edit quantities or re-run control from that tab.

## Scope

### In Scope

- When `estado === 'controlado'`, render all `saldos.lineas` (including saldo 0)
- Read-only table (no checkboxes, tanda inputs, faltantes form, or control action buttons)
- Keep zero-saldo hide for `recibido` / `con_faltantes`
- Tests for Controlados exhibit + no-regress on faltantes hide
- Short guia note if the Controlados section exists

### Out of Scope

- Backend / `computar_saldos` / estado transitions
- New tabs or permisos
- Pedidos list / ModalPedidoDetalle
- Desvincular per OC

## Capabilities

### Modified Capabilities

- `recepcion-deposito`: Controlados CON-OC OC lines are visible and read-only

## Approach

Gate inside `AccordionBodyConOc` on `pedido.estado === 'controlado'`. Use unfiltered `lineasErp` for display; reuse the arribo-style read-only columns (ítem, depósito, cant. pedida; optionally recibido/saldo as display-only). Hide control UI. Do not change the filter for other estados.

**Apply:** branch `fix/compras-deposito-controlados-oc-readonly` from **main**. PR to **main**.

## Success Criteria

- [ ] Controlados + all saldos 0 → OC ítems visible
- [ ] Controlados → no Marcar / tanda / faltantes controls
- [ ] Recibido with mixed saldos → saldo 0 lines still hidden
