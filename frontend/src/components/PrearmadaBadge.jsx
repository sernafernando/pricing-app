import { Package } from 'lucide-react';
import styles from './PrearmadaBadge.module.css';

/**
 * Displays a compact pill badge showing prearmadas availability for an item.
 *
 * Render logic:
 *   - stats.exact > 0           → green badge  "{exact} listas"
 *   - exact === 0 && upgrade > 0 → yellow badge "{upgrade} disponibles (upgrade)"
 *   - else (zeros or no stats)  → renders nothing
 *
 * @param {{ stats: { exact: number, upgrade: number } | null | undefined }} props
 */
export default function PrearmadaBadge({ stats }) {
  if (!stats) return null;

  const { exact = 0, upgrade = 0 } = stats;

  if (exact === 0 && upgrade === 0) return null;

  const isExact = exact > 0;
  const label = isExact
    ? `${exact} lista${exact === 1 ? '' : 's'}`
    : `${upgrade} disponible${upgrade === 1 ? '' : 's'} (upgrade)`;

  const tooltip = `Prearmadas — Exactas: ${exact} | Upgrade: ${upgrade}`;

  return (
    <span
      className={`${styles.badge} ${isExact ? styles.exact : styles.upgrade}`}
      title={tooltip}
      aria-label={tooltip}
    >
      <Package size={11} aria-hidden />
      <span className={styles.label}>{label}</span>
    </span>
  );
}
