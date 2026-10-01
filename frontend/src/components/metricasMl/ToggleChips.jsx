import facetStyles from '../ventasMl/FacetChips.module.css';
import styles from './ToggleChips.module.css';

const INT_FORMAT = new Intl.NumberFormat('es-AR');

/**
 * Multi-select chips with live counts (Métricas ML "Publicación:" and
 * "Tipo:" rows): same look as the Ventas ML `FacetChips`, but each chip
 * toggles on its own -- no "Todas", nothing selected means no filter.
 * Counts come from the backend's facets, never recomputed here.
 */
export default function ToggleChips({ label, options, labels, counts, selected, onChange, dotFor }) {
  const toggle = (value) =>
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value]);
  return (
    <div className={facetStyles.row} role="group" aria-label={label}>
      {options.map((value) => {
        const active = selected.includes(value);
        return (
          <button
            key={value}
            type="button"
            className={`${facetStyles.chip} ${active ? facetStyles.chipActive : ''}`}
            aria-pressed={active}
            onClick={() => toggle(value)}
          >
            {dotFor?.(value) && <span className={styles.dot} data-tone={dotFor(value)} aria-hidden="true" />}
            <span>{labels[value] ?? value}</span>{' '}
            {counts && (
              <>
                <span className={facetStyles.srOnly}>·</span>{' '}
                <span className={facetStyles.count}>{INT_FORMAT.format(counts[value] ?? 0)}</span>
              </>
            )}
          </button>
        );
      })}
    </div>
  );
}
