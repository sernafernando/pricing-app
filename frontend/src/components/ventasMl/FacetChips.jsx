import styles from './FacetChips.module.css';

/**
 * FacetChips — ventas-ml-rediseno PR14.T7/T8 (LISTING R30, design D13).
 *
 * A pure renderer for one filter axis's live facet counts. This component
 * NEVER recomputes a count: `total` and every `counts[value]` come from
 * the backend's own `facets` response for the CURRENT combined filter set
 * (the other axis, search, date range...) — the consistency bug this
 * component must not reintroduce was counting client-side once already.
 *
 * Extracted from the inline chip rows `VentasML.jsx` used to render
 * per-axis (operation_status, goods_status) — same markup/behavior, now
 * shared so both axes stay visibly identical instead of two copies that
 * can drift.
 */
export default function FacetChips({ label, options, labels, counts, total, activeValue, onChange }) {
  return (
    <div className={styles.row} role="group" aria-label={label}>
      <button
        type="button"
        className={`${styles.chip} ${activeValue === '' ? styles.chipActive : ''}`}
        aria-pressed={activeValue === ''}
        onClick={() => onChange('')}
      >
        Todas · {total ?? 0}
      </button>
      {options.map((value) => (
        <button
          key={value}
          type="button"
          className={`${styles.chip} ${activeValue === value ? styles.chipActive : ''}`}
          aria-pressed={activeValue === value}
          onClick={() => onChange(activeValue === value ? '' : value)}
        >
          {labels[value] ?? value} · {counts?.[value] ?? 0}
        </button>
      ))}
    </div>
  );
}
