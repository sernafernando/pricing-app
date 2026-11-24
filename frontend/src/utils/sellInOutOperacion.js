/**
 * The sell out amount a sale's tooltip names (Ventas ML, sell-in-sell-out T14).
 *
 * A USD sell out whose rate is not defined yet is `sell_out_estimado`. There is no sell in per sale any more
 * (costo SI T5 PR B: it is inside the costo SI), so no tooltip names one, and the Ventas fuera de ML operations list
 * has no "c/ sell in" cells.
 */

const ESTIMADO = ' (estimado: tipo de cambio a definir)';

/** The amounts a sale's sell in / sell out tooltip names, shared by every list that shows them: the sell out only. */
export const partesSellInOut = (op, moneda) => {
  const partes = [];
  if (op.sell_out_ars != null) {
    partes.push(`Sell out: ${moneda(op.sell_out_ars)}${op.sell_out_estimado ? ESTIMADO : ''}`);
  } else if (op.sell_out_estimado) {
    partes.push('Sell out en USD sin tipo de cambio');
  }
  return partes;
};

/** A sale's sell out line in Ventas ML: `out ≈` while estimated, `a definir` while unknown, null without one. */
export const lineaSellOut = (op, moneda) => {
  if (op.sell_out_ars != null) return `out ${op.sell_out_estimado ? '≈ ' : ''}${moneda(op.sell_out_ars)}`;
  return op.sell_out_estimado ? 'out a definir' : null;
};
