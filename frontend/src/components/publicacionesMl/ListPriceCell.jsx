import { formatAmount } from '../../utils/ventasMlFormat';
import { formatPct } from '../../utils/metricasMlFormat';
import styles from './cells.module.css';

/**
 * One of Productos' prices of a row's product (`column`: its `price` and `markup` fields, and `takesPart`, the flag
 * without which Productos shows no price). The markup only with `canSeeMargin`. No product reads "—" ("…" while
 * its prices are on their way), and so does a price that is not there: never 0.
 */
export default function ListPriceCell({ product, column, loading, canSeeMargin }) {
  if (!product) return <span className={styles.empty}>{loading ? '…' : '—'}</span>;
  const amount = product[column.price];
  if (amount == null || Number(amount) <= 0 || (column.takesPart && !product[column.takesPart])) {
    return <span className={styles.empty}>—</span>;
  }
  const markup = product[column.markup];
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      <span className={styles.amount}>{formatAmount(amount)}</span>
      {canSeeMargin && markup != null && (
        <span className={styles.markup} data-negative={Number(markup) < 0 ? '' : undefined}>
          {formatPct(markup)}
        </span>
      )}
    </div>
  );
}
