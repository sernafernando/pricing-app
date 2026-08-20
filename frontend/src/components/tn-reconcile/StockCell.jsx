import styles from '../../pages/TiendaNubeReconcile.module.css';

// Stock cell: unknown stock (`null`) MUST render distinctly from a real
// zero — `0` is exactly the value that raises `despublicar` on the backend,
// so collapsing "unknown" into "0" (or into a blank cell that reads the same
// as zero) would be a real defect (design.md Decision 3). An em dash is
// visibly non-numeric, unlike "0" or an empty string.
const STOCK_UNKNOWN_LABEL = '—';

export default function StockCell({ row }) {
  // Muted (.noLink), same treatment as DuplicateGroupCard/BANLIST's
  // empty-value dash — never plain unstyled body text.
  return row.stock === null || row.stock === undefined ? (
    <span className={styles.noLink}>{STOCK_UNKNOWN_LABEL}</span>
  ) : (
    String(row.stock)
  );
}
