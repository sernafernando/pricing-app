import { formatPct, formatUnits } from '../../utils/metricasMlFormat';
import { formatAmount } from '../../utils/ventasMlFormat';
import styles from './cells.module.css';

/**
 * Cells of the 30-day sales summary (`row.sales_30d`), the figures of Métricas
 * ML's own base computed by the server. A publication without sales reads "—",
 * never 0.
 */
const hasSales = (sales) => Number(sales?.units ?? 0) > 0;

/** Units sold and gross revenue over the last 30 days (`ml_metricas.ver`). */
export function Sales30dCell({ sales }) {
  if (!hasSales(sales)) return <span className={styles.empty}>—</span>;
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      <span className={styles.amount}>{`${formatUnits(sales.units)} u.`}</span>
      <span className={styles.note}>{formatAmount(sales.gross)}</span>
    </div>
  );
}

/** Real (sales-weighted) markup of those sales (`ml_metricas.ver_ganancia`); "—" without sales or cost. */
export function Markup30dCell({ sales }) {
  if (!hasSales(sales) || sales.markup == null) return <span className={styles.empty}>—</span>;
  return (
    <span className={styles.markup} data-negative={sales.markup < 0 ? '' : undefined}>
      {formatPct(sales.markup)}
    </span>
  );
}
