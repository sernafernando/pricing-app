# Proposal: Pedido detail OC table — código, descripción, multi-OC

## Intent

Pedido detail OC breakdown shows depósito + item_id and only the first linked OC. Operators need product `codigo` (same as Depósito `itemCodigo`), description with ellipsis, centered qty/saldo, and one stacked table per linked OC.

## Scope

### In Scope

- Columns: Código | Descripción | Qty OC | Saldo pendiente (no depósito, no item_id)
- Descripción from `item_nombre`; ellipsis if long
- Código from `productos_erp.codigo` (`item_code`)
- Center Qty OC and Saldo (header + cells)
- One table per linked OC when N>1 (title `OC #poh`)
- Backend detalle returns lines for every linked triple + `item_code` + per-line OC ids
- Tests (detalle multi-OC + ModalPedidoDetalle)

### Out of Scope

- Depósito Controlados (sibling change on same branch)
- Changing saldo formula

## Approach

Extend `get_orden_compra_detalle` with `triples_for_pedido` (like saldos). Keep top-level first-triple fields for compat. Frontend groups lines by `oc_poh_id`.

Branch: same `fix/compras-deposito-controlados-oc-readonly`. PR to **main**.
