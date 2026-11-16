import chipStyles from '../kit/FacetChips.module.css';
import styles from './VendedorFilter.module.css';

// How many salespeople get a chip of their own on Por fuera (approved mockup 2); the rest go in "Otro".
const TOP_CHIPS = 3;
const INT_FORMAT = new Intl.NumberFormat('es-AR');
// GBP prints the salesperson on documents cut to this many characters: the board lists those cut names, while an
// upload's "Ver métricas" link carries the report header's full name (backend LARGO_VENDEDOR_IMPRESO).
const LARGO_VENDEDOR_IMPRESO = 12;

/** The board's option a chosen name stands for: itself, or the option that is its cut to 12 characters. */
function comoOpcion(name, options) {
  if (options.includes(name) || name.length <= LARGO_VENDEDOR_IMPRESO) return name;
  const cortado = name.slice(0, LARGO_VENDEDOR_IMPRESO);
  return options.includes(cortado) ? cortado : name;
}

// The select's value while a link carries several salespeople (not a salesperson name).
const VARIOS = '\u0000varios';

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

/** The top salespeople by documents (ties and missing counts keep the board's order), the chosen ones always among
 * them. */
function topNames(options, counts, elegidos) {
  const ranked = counts
    ? options
        .map((name, index) => ({ name, index, n: counts[name] ?? 0 }))
        .sort((a, b) => b.n - a.n || a.index - b.index)
        .map(({ name }) => name)
    : options;
  const top = ranked.slice(0, TOP_CHIPS);
  for (const name of elegidos) if (!top.includes(name)) top.push(name);
  return top;
}

/**
 * The ventas por fuera salesperson filter (vpf-metricas-canal-fe, approved mockups 1 and 2): one salesperson or all
 * of them (`facets.vendedores`, narrowed by the empresa chosen). `chips` (Por fuera) shows "Todos" and the
 * salespeople with most documents (`counts`, `facets.vendedor_documentos`) as chips with their counts, the rest in
 * "Otro"; `select` (Todo) is one dropdown. The board answers for the names. `value` is the name chosen or the list a
 * link carries (a load that imported several salespeople): every one of them shows as chosen; `onChange` gets one.
 */
export default function VendedorFilter({ options = [], counts, value = '', onChange, variant = 'select' }) {
  const elegidos = (Array.isArray(value) ? value : [value]).filter(Boolean).map((name) => comoOpcion(name, options));
  const solo = elegidos.length === 1 ? elegidos[0] : '';
  if (variant === 'chips') {
    const top = topNames(options, counts, elegidos);
    const others = options.filter((name) => !top.includes(name));
    return (
      <div className={chipStyles.row} role="group" aria-label="Vendedores">
        <button
          type="button"
          className={`${chipStyles.chip} ${elegidos.length === 0 ? chipStyles.chipActive : ''}`}
          aria-pressed={elegidos.length === 0}
          onClick={() => onChange('')}
        >
          Todos
        </button>
        {top.map((name) => (
          <button
            key={name}
            type="button"
            className={`${chipStyles.chip} ${elegidos.includes(name) ? chipStyles.chipActive : ''}`}
            aria-pressed={elegidos.includes(name)}
            onClick={() => onChange(solo === name ? '' : name)}
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
    <select
      className={styles.select}
      aria-label="Vendedor"
      value={elegidos.length > 1 ? VARIOS : solo}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">Todos los vendedores</option>
      {elegidos.length > 1 && (
        <option value={VARIOS} disabled>
          {elegidos.length} vendedores
        </option>
      )}
      {/* A salesperson chosen from a link that the period does not list stays selectable. */}
      {[...(solo && !options.includes(solo) ? [solo] : []), ...options].map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
  );
}
