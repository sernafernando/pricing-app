/**
 * The sell in / sell out amounts a sale's tooltip names (Ventas ML, sell-in-sell-out T14).
 *
 * A USD sell out whose rate is not defined yet is `sell_out_estimado`. The Ventas fuera de ML operations list no
 * longer has "c/ sell in" cells (costo SI T5 PR B): its fields were always null and are gone.
 */

const ESTIMADO = ' (estimado: tipo de cambio a definir)';

const parteSellIn = (op, moneda) => `Sell in: ${moneda(op.sell_in_ars)}${op.sell_in_estimado ? ESTIMADO : ''}`;

/** The amounts a sale's sell in / sell out tooltip names, shared by every list that shows them. */
export const partesSellInOut = (op, moneda) => {
  const partes = [];
  if (op.sell_in_ars != null) partes.push(parteSellIn(op, moneda));
  if (op.sell_out_ars != null) {
    partes.push(`Sell out: ${moneda(op.sell_out_ars)}${op.sell_out_estimado ? ESTIMADO : ''}`);
  } else if (op.sell_out_estimado) {
    partes.push('Sell out en USD sin tipo de cambio');
  }
  return partes;
};

/** A sale's sell out under its sell in in Ventas ML: `out ≈` while estimated, `a definir` while unknown, null without one. */
export const lineaSellOut = (op, moneda) => {
  if (op.sell_out_ars != null) return `out ${op.sell_out_estimado ? '≈ ' : ''}${moneda(op.sell_out_ars)}`;
  return op.sell_out_estimado ? 'out a definir' : null;
};
