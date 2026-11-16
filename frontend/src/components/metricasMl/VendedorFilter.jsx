import chipStyles from '../kit/FacetChips.module.css';
import styles from './VendedorFilter.module.css';

// How many salespeople get a chip of their own on Por fuera (approved mockup 2); the rest go in "Otro".
const TOP_CHIPS = 3;
const INT_FORMAT = new Intl.NumberFormat('es-AR');

/** "Vendedora Uno · 96" -- the " · " kept for the accessible name and hidden on screen, like FacetChips. */
function Name({ name, count }) {
  if (count === undefined || count === null) return name;
  return (
    <>
      <span>{name}</span> <span className={chipStyles.srOnly}>·</span>{' '}
      <span className={chipStyles.count}>{INT_FORMAT.format(count)}</span>
    </>
  );
}

/** The top salespeople by documents (ties and missing counts keep the board's order), the chosen one always among
 * them. */
function topNames(options, counts, value) {
  const ranked = counts
    ? options
        .map((name, index) => ({ name, index, n: counts[name] ?? 0 }))
        .sort((a, b) => b.n - a.n || a.index - b.index)
        .map(({ name }) => name)
    : options;
  const top = ranked.slice(0, TOP_CHIPS);
  if (value && !top.includes(value)) top.push(value);
  return top;
}

/**
 * The ventas por fuera salesperson filter (vpf-metricas-canal-fe, approved mockups 1 and 2): one salesperson or all
 * of them (`facets.vendedores`, narrowed by the empresa chosen). `chips` (Por fuera) shows "Todos" and the
 * salespeople with most documents (`counts`, `facets.vendedor_documentos`) as chips with their counts, the rest in
 * "Otro"; `select` (Todo) is one dropdown. The board answers for the names.
 */
export default function VendedorFilter({ options = [], counts, value = '', onChange, variant = 'select' }) {
  if (variant === 'chips') {
    const top = topNames(options, counts, value);
    const others = options.filter((name) => !top.includes(name));
    return (
      <div className={chipStyles.row} role="group" aria-label="Vendedores">
        <button
          type="button"
          className={`${chipStyles.chip} ${value === '' ? chipStyles.chipActive : ''}`}
          aria-pressed={value === ''}
          onClick={() => onChange('')}
        >
          Todos
        </button>
        {top.map((name) => (
          <button
            key={name}
            type="button"
            className={`${chipStyles.chip} ${value === name ? chipStyles.chipActive : ''}`}
            aria-pressed={value === name}
            onClick={() => onChange(value === name ? '' : name)}
          >
            <Name name={name} count={counts?.[name]} />
          </button>
        ))}
        {others.length > 0 && (
          <select
            className={`${styles.select} ${styles.compact}`}
            aria-label="Vendedor"
            value=""
            onChange={(event) => onChange(event.target.value)}
          >
            <option value="">Otro</option>
            {others.map((name) => (
              <option key={name} value={name}>
                {counts?.[name] == null ? name : `${name} · ${INT_FORMAT.format(counts[name])}`}
              </option>
            ))}
          </select>
        )}
      </div>
    );
  }
  return (
    <select className={styles.select} aria-label="Vendedor" value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">Todos los vendedores</option>
      {/* A salesperson chosen from a link that the period does not list stays selectable. */}
      {[...(value && !options.includes(value) ? [value] : []), ...options].map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
  );
}
