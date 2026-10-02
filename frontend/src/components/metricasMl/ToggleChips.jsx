import { EyeOff } from 'lucide-react';
import facetStyles from '../ventasMl/FacetChips.module.css';
import styles from './ToggleChips.module.css';

const INT_FORMAT = new Intl.NumberFormat('es-AR');

/**
 * Tri-state chips with live counts (Métricas ML "Publicación:" and "Tipo:"
 * rows): same look as the Ventas ML `FacetChips`, but each chip cycles on its
 * own -- neutral -> "solo estas" (include) -> "ocultar" (exclude) -> neutral.
 * No "Todas": nothing selected and nothing excluded means no filter.
 * `onChange(selected, excluded)` always hands over BOTH lists, so a chip can
 * never end up in both. Counts come from the backend's facets, never
 * recomputed here (they ignore this group's own include AND exclude, so an
 * excluded chip still shows how many it is hiding).
 */
export default function ToggleChips({ label, options, labels, counts, selected, excluded = [], onChange, dotFor }) {
  const cycle = (value) => {
    if (excluded.includes(value)) return onChange(selected, excluded.filter((v) => v !== value));
    if (selected.includes(value)) return onChange(selected.filter((v) => v !== value), [...excluded, value]);
    return onChange([...selected, value], excluded);
  };
  return (
    <div className={facetStyles.row} role="group" aria-label={label}>
      {options.map((value) => {
        const state = excluded.includes(value) ? 'exclude' : selected.includes(value) ? 'include' : 'neutral';
        const name = labels[value] ?? value;
        return (
          <button
            key={value}
            type="button"
            className={`${facetStyles.chip} ${state === 'include' ? facetStyles.chipActive : ''} ${
              state === 'exclude' ? styles.chipExcluded : ''
            }`}
            data-state={state}
            aria-pressed={state !== 'neutral'}
            aria-label={
              state === 'exclude'
                ? `Ocultar ${name}${counts ? ` · ${INT_FORMAT.format(counts[value] ?? 0)}` : ''}`
                : undefined
            }
            title={state === 'exclude' ? 'Oculta: clic para quitar el filtro' : undefined}
            onClick={() => cycle(value)}
          >
            {state === 'exclude' ? (
              <EyeOff size={12} aria-hidden="true" />
            ) : (
              dotFor?.(value) && <span className={styles.dot} data-tone={dotFor(value)} aria-hidden="true" />
            )}
            <span className={state === 'exclude' ? styles.struck : undefined}>{name}</span>{' '}
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
