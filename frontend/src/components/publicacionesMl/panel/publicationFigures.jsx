import HeaderMarkup from './HeaderMarkup';
import { amount, count, units } from './format';
import { SellInCost, SellInOutMarkupLine } from './sellInOutFigures';
import styles from './panel.module.css';

const money = (value) => {
  const formatted = amount(value);
  return formatted == null ? null : `$ ${formatted}`;
};

/**
 * The header figures of a publication (S1), from its list row, each under its
 * label as the approved design shows them (owner, P3: the labels once per card,
 * never on each row). The price with "Markup <value>" under it in its tone, the
 * markup only with `ml_metricas.ver_ganancia`. Then Stock, and Ventas 30 días only
 * with `ml_metricas.ver` (the table's own figures), and only once the detail sends
 * them (`sales_30d`, absent from an older backend). With `ml_metricas.ver_ganancia`, the markup with sell in /
 * sell out under the markup (S9) and a Costo card (S6) from the detail's `markup_breakdown` and `sell_in_out`.
 */
/** Which unit the breakdown explains (L11): the cost and the sell in/out markup are that unit's, the markup above is
 * the publication's range. Same wording as Rentabilidad's "Unidad calculada". */
const unitHint = (breakdown) =>
  breakdown?.variation_id == null ? 'Unidad calculada: la publicación' : `Unidad calculada: variación ${breakdown.variation_id}, la de peor markup`;

export function publicationFigures(row, { canSeeMargin, canSeeSales, breakdown = null, sellInOut = null }) {
  const price = money(row.price?.amount);
  const hint = unitHint(breakdown);
  const figures = [
    {
      key: 'price',
      label: 'Precio',
      value: price && <span title="Precio">{price}</span>,
      note: canSeeMargin ? (
        <>
          <HeaderMarkup markup={row.markup} />
          {/* S9: the markup with the product's sell in / sell out today, as Rentabilidad shows it. */}
          <SellInOutMarkupLine sellInOut={sellInOut} className={styles.figureSubnote} labelClassName={styles.figureMarkupWord} labelTitle={hint} />
        </>
      ) : null,
    },
  ];
  // S6: the product's cost in pesos (the one the markup divides by) and, under it, the cost with sell in.
  if (canSeeMargin && breakdown?.costo_ars != null) {
    const sellIn = sellInOut?.sell_in;
    figures.push({
      key: 'cost',
      label: 'Costo',
      value: <span title={`Costo del producto en pesos. ${hint}`}>{money(breakdown.costo_ars)}</span>,
      note: sellIn ? (
        <>
          c/ sell in <SellInCost sellIn={sellIn} format={money} />
        </>
      ) : null,
    });
  }
  figures.push(
    // The table's stock total (ERP + Full), never the published quantity; its parts are the Resumen's (each datum once).
    { key: 'stock', label: 'Stock', value: units(row.stock_total), note: row.stock_total == null ? null : 'ERP + Full' },
  );
  if (canSeeSales && row.sales_30d !== undefined) {
    const sales = row.sales_30d;
    figures.push({
      key: 'sales',
      label: 'Ventas 30 días',
      value: count(sales?.units),
      // The amount wraps whole, never between its "$" and its digits.
      note: sales?.gross == null ? null : <>Facturado <span className={styles.nowrap}>{money(sales.gross)}</span></>,
    });
  }
  return figures;
}
