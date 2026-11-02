import HeaderMarkup from './HeaderMarkup';
import { amount, count } from './format';
import styles from './panel.module.css';

const money = (value) => {
  const formatted = amount(value);
  return formatted == null ? null : `$ ${formatted}`;
};

/**
 * The header figures of a publication (S1), from its list row. The price with its
 * markup right below in another colour, without labels (owner: "si vos ponés
 * $100.000 y abajo 5% y con colores distintos se entiende cual es el precio y cual
 * el markup"); the markup only with `ml_metricas.ver_ganancia`. Then Stock, and
 * Ventas 30 días only with `ml_metricas.ver` (the table's own figures). The body
 * does not repeat them.
 */
export function publicationFigures(row, { canSeeMargin, canSeeSales }) {
  const stock = row.stock ?? {};
  const split = stock.full == null && stock.own == null ? null : `Full ${count(stock.full) ?? 0} · propio ${count(stock.own) ?? 0}`;
  const price = money(row.price?.amount);
  const figures = [
    {
      key: 'price',
      label: canSeeMargin ? 'Precio y markup' : 'Precio',
      hideLabel: true,
      value: price && (
        <span title="Precio">
          <span className={styles.visuallyHidden}>Precio </span>
          {price}
        </span>
      ),
      note: canSeeMargin ? <HeaderMarkup markup={row.markup} /> : null,
    },
    { key: 'stock', label: 'Stock', value: count(stock.available), note: split },
  ];
  if (canSeeSales) {
    const sales = row.sales_30d;
    figures.push({
      key: 'sales',
      label: 'Ventas 30 días',
      value: count(sales?.units),
      note: sales?.gross == null ? null : `Facturado ${money(sales.gross)}`,
    });
  }
  return figures;
}

