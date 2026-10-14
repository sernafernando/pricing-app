import styles from './cells.module.css';

/**
 * ERP stock of the linked product (depósito 1, the figure Productos shows),
 * from its own source and never merged with the ML stock. `null` means the
 * publication has no linked product: unknown, shown as "—", never 0. A real
 * zero (or less) is shown and flagged.
 */
export default function ErpStockCell({ erpStock }) {
  const quantity = erpStock?.quantity ?? null;
  if (quantity == null) return <span className={styles.empty}>—</span>;
  const out = quantity <= 0;
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      <span className={`${styles.units} ${out ? styles.outOfStock : ''}`}>{quantity}</span>
      {out && <span className={`${styles.note} ${styles.outOfStock}`}>Sin stock ERP</span>}
    </div>
  );
}
