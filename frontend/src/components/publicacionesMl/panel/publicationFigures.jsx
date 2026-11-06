import HeaderMarkup from './HeaderMarkup';
import { amount, count } from './format';
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
 * them (`sales_30d`, absent from an older backend).
 */
export function publicationFigures(row, { canSeeMargin, canSeeSales }) {
  const stock = row.stock ?? {};
  const price = money(row.price?.amount);
  const figures = [
    {
      key: 'price',
      label: 'Precio',
      value: price && <span title="Precio">{price}</span>,
      note: canSeeMargin ? <HeaderMarkup markup={row.markup} /> : null,
    },
    // The total only: Full and propio are the Resumen's stock breakdown (each datum once).
    { key: 'stock', label: 'Stock', value: count(stock.available), note: stock.available == null ? null : 'unidades' },
  ];
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
