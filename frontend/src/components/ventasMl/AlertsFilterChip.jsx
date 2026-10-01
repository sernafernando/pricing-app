import styles from './AlertsFilterChip.module.css';

/**
 * "Solo con alertas  [19]  (switch)": the design's toggle at the end of the
 * filter card's first band. Still one pressable button (`aria-pressed`) whose
 * accessible name reads "Solo con alertas · N" -- the " · " is visually
 * hidden. `count` is the backend's `facets.alerts_total` (groups with an
 * alert in the scope every other filter leaves standing) -- never derived
 * here.
 */
export default function AlertsFilterChip({ active, count, onChange }) {
  return (
    <button
      type="button"
      className={`${styles.toggle} ${active ? styles.toggleOn : ''}`}
      aria-pressed={active}
      onClick={() => onChange(!active)}
    >
      <span className={styles.label}>Solo con alertas</span> <span className={styles.srOnly}>·</span>{' '}
      <span className={styles.count}>{count ?? 0}</span>
      <span className={styles.track} aria-hidden="true">
        <span className={styles.thumb} />
      </span>
    </button>
  );
}
