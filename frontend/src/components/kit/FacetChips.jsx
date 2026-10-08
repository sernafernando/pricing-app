import styles from './FacetChips.module.css';

const INT_FORMAT = new Intl.NumberFormat('es-AR');

/**
 * FacetChips — ventas-ml-rediseno PR14.T7/T8 (LISTING R30, design D13).
 *
 * A pure renderer for one filter axis's live facet counts. This component
 * NEVER recomputes a count: `total` and every `counts[value]` come from
 * the backend's own `facets` response for the CURRENT combined filter set
 * (the other axis, search, date range...) — the consistency bug this
 * component must not reintroduce was counting client-side once already.
 *
 * Looks like the Stitch `listado` chips: label + count, the active one
 * filled with the primary colour. The " · " between them is kept in the
 * DOM (visually hidden) so the accessible name still reads "Pagada · 3".
 */
function ChipContent({ label, count }) {
  return (
    <>
      {/* The spaces are separate text nodes on purpose: the accessible name
          keeps them ("Pagada · 3"), the flex layout drops them. */}
      <span>{label}</span> <span className={styles.srOnly}>·</span>{' '}
      <span className={styles.count}>{INT_FORMAT.format(count ?? 0)}</span>
    </>
  );
}

export default function FacetChips({ label, options, labels, counts, total, activeValue, onChange }) {
  return (
    <div className={styles.row} role="group" aria-label={label}>
      <button
        type="button"
        className={`${styles.chip} ${activeValue === '' ? styles.chipActive : ''}`}
        aria-pressed={activeValue === ''}
        onClick={() => onChange('')}
      >
        <ChipContent label="Todas" count={total} />
      </button>
      {options.map((value) => (
        <button
          key={value}
          type="button"
          className={`${styles.chip} ${activeValue === value ? styles.chipActive : ''}`}
          aria-pressed={activeValue === value}
          onClick={() => onChange(activeValue === value ? '' : value)}
        >
          <ChipContent label={labels[value] ?? value} count={counts?.[value]} />
        </button>
      ))}
    </div>
  );
}
