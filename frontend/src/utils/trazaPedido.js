// Orders of the trace views. An ERP order number repeats across branches, and an ML sale no ERP order stands for
// comes with soh_id 0 (e.g. an order known only to Ventas ML), so neither soh_id alone identifies an order.

export const pedidoKey = (pedido) => `${pedido.bra_id ?? ''}-${pedido.soh_id ?? ''}-${pedido.ml_id ?? ''}`;

export const pedidoLabel = (pedido) =>
  pedido.soh_id ? `#${pedido.soh_id}` : pedido.ml_id ? `Venta ML #${pedido.ml_id}` : '—';
