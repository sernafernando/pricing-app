import styles from './FacetChips.module.css';

/**
 * "Solo con alertas · N": one pressable chip, same look as the facet chips.
 * `count` is the backend's `facets.alerts_total` (groups with an alert in the
 * scope every other filter leaves standing) -- never derived here.
 */
export default function AlertsFilterChip({ active, count, onChange }) {
  return (
    <div className={styles.row}>
      <button
        type="button"
        className={`${styles.chip} ${active ? styles.chipActive : ''}`}
        aria-pressed={active}
        onClick={() => onChange(!active)}
      >
        Solo con alertas · {count ?? 0}
      </button>
    </div>
  );
}
