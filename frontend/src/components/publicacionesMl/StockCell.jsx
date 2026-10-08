import styles from './cells.module.css';

/**
 * `available` is the headline; Full / Propio only when the store knows them
 * (null is "unknown", not zero: a user product without a stock row has no
 * Full figure). A real 0 is shown as 0 and flagged.
 */
export default function StockCell({ stock }) {
  const available = stock?.available ?? null;
  const full = stock?.full ?? null;
  const own = stock?.own ?? null;
  if (available == null && full == null && own == null) return <span className={styles.empty}>—</span>;
  const detail = [full != null && `Full ${full}`, own != null && `Propio ${own}`].filter(Boolean).join(' · ');
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      {available == null ? (
        <span className={styles.empty}>—</span>
      ) : (
        <span className={`${styles.units} ${available === 0 ? styles.outOfStock : ''}`}>{available}</span>
      )}
      {available === 0 && <span className={`${styles.note} ${styles.outOfStock}`}>Sin stock</span>}
      {detail && <span className={styles.note}>{detail}</span>}
    </div>
  );
}
