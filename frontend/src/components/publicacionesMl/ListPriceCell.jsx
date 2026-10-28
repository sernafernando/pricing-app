import { formatAmount } from '../../utils/ventasMlFormat';
import { formatPct } from '../../utils/metricasMlFormat';
import styles from './cells.module.css';

/**
 * One of Productos' prices of a row's product (`column`: its `price` and `markup` fields, and `takesPart`, the flag
 * without which Productos shows no price). The markup only with `canSeeMargin`. No product reads "—" ("…" while
 * its prices are on their way), and so does a price that is not there: never 0. `markupScale` turns the markup the
 * listing sends into a percentage (the best offer's comes as a fraction). A failed request (`failed`) reads
 * "sin datos", never "—", so it is not taken for a product with no price. `column.details(product)`, when the
 * column has it, lists lines drawn under the price (the best offer's, as Productos).
 */
export default function ListPriceCell({ product, column, loading, failed, canSeeMargin }) {
  if (failed) {
    return (
      <span className={styles.empty} title="No se pudieron cargar los precios de Productos">
        sin datos
      </span>
    );
  }
  if (!product) return <span className={styles.empty}>{loading ? '…' : '—'}</span>;
  const amount = product[column.price];
  if (amount == null || Number(amount) <= 0 || (column.takesPart && !product[column.takesPart])) {
    return <span className={styles.empty}>—</span>;
  }
  const raw = product[column.markup];
  const markup = raw == null ? null : Number(raw) * column.markupScale;
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      <span className={styles.amount}>{formatAmount(amount)}</span>
      {canSeeMargin && markup != null && (
        <span className={styles.markup} data-negative={Number(markup) < 0 ? '' : undefined}>
          {formatPct(markup)}
        </span>
      )}
      {column.details?.(product).map((line) => (
        <span key={line} className={styles.priceDetail} data-offer-detail="">
          {line}
        </span>
      ))}
    </div>
  );
}
