import styles from './cells.module.css';
import { formatUnits } from '../../utils/metricasMlFormat';

/**
 * ERP stock of the linked product (depósito 1, the figure Productos shows),
 * from its own source and never merged with the ML stock. `null` means the
 * publication has no linked product: unknown, shown as "—", never 0. A real
 * zero (or less) is shown in the danger tone, "Sin stock ERP" in its tooltip and
 * for screen readers: a note under it would make the column wider than its figures.
 */
export default function ErpStockCell({ erpStock }) {
  const quantity = erpStock?.quantity ?? null;
  if (quantity == null) return <span className={styles.empty}>—</span>;
  const out = quantity <= 0;
  return (
    <div className={`${styles.stack} ${styles.stackEnd} ${styles.srHost}`} title={out ? 'Sin stock ERP' : undefined}>
      <span className={`${styles.units} ${out ? styles.outOfStock : ''}`}>{formatUnits(quantity)}</span>
      {out && <span className={styles.srOnly}>Sin stock ERP</span>}
    </div>
  );
}
