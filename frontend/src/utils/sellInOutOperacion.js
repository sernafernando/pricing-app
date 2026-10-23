/**
 * The "with sell in / sell out" cells of an operation in the operations lists (`GET .../operaciones`,
 * sell-in-sell-out T14): the cost with sell in and the markup with sell in and sell out, next to the
 * figures without them.
 *
 * The API leaves every field null for an operation without either; a USD sell out whose rate is not
 * defined yet is `sell_out_estimado`, and its markup is null while the amount itself is unknown.
 */

const montos = (op, moneda) => {
  const partes = [];
  if (op.sell_in_ars != null) partes.push(`Sell in: ${moneda(op.sell_in_ars)}`);
  if (op.sell_out_ars != null) {
    partes.push(`Sell out: ${moneda(op.sell_out_ars)}${op.sell_out_estimado ? ' (estimado: tipo de cambio a definir)' : ''}`);
  } else if (op.sell_out_estimado) {
    partes.push('Sell out en USD sin tipo de cambio');
  }
  return partes;
};

/** `{ costo, markup }` cells: `texto`, the `title` naming the amounts, and whether the markup is negative. */
export const celdasSellInOut = (op, { moneda, porcentaje }) => {
  if (op.costo_con_sell_in == null) {
    return { costo: { texto: '-', title: undefined }, markup: { texto: '-', title: undefined, negativo: false } };
  }
  const partes = montos(op, moneda);
  const markup = op.markup_con_sell_in_out;
  let texto = 'A definir';
  if (markup != null) texto = `${op.sell_out_estimado ? '≈ ' : ''}${porcentaje(markup)}`;
  return {
    costo: { texto: moneda(op.costo_con_sell_in), title: op.sell_in_ars != null ? `Sell in: ${moneda(op.sell_in_ars)}` : undefined },
    markup: { texto, title: partes.join(' · ') || undefined, negativo: markup != null && Number(markup) < 0 },
  };
};
