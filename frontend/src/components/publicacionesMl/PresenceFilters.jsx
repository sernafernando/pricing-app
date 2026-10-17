import { FilterX, X } from 'lucide-react';
import { EMPTY_PRESENCE_FILTERS, PRESENCE_FILTERS, activePresenceChips } from './presenceFilters';
import chipStyles from './ProductFilters.module.css';
import styles from './PresenceFilters.module.css';

/**
 * The "Presencia:" group of the Publicaciones ML filter card: Productos' "Filtros de Presencia" (rebate, mejor
 * oferta, web transferencia, Tienda Nube, out of cards), each a Todos / con / sin select as in Productos, plus one
 * removable chip per active toggle and a control that clears the five. The values live in the URL
 * (`usePublicacionesMLFilters`), so every view asks its endpoint with them.
 *
 * @param {{filters: object, setFilters: (updates: object) => void, labelClassName?: string}} props
 */
export default function PresenceFilters({ filters, setFilters, labelClassName }) {
  const chips = activePresenceChips(filters);

  return (
    <div className={chipStyles.group}>
      <span className={labelClassName}>Presencia:</span>
      {PRESENCE_FILTERS.map(({ key, icon: Icon, name, options }) => (
        <label key={key} className={styles.item}>
          <span aria-hidden="true" className={styles.name}>
            {Icon && <Icon size={12} aria-hidden="true" />}
            {name}
          </span>
          <select
            aria-label={name}
            className={styles.select}
            value={filters[key] || 'todos'}
            onChange={(event) => setFilters({ [key]: event.target.value === 'todos' ? '' : event.target.value })}
          >
            <option value="todos">Todos</option>
            {options.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      ))}
      {chips.length > 0 && (
        <ul className={chipStyles.chips} aria-label="Filtros de presencia activos">
          {chips.map((chip) => (
            <li key={chip.id}>
              <button
                type="button"
                className={chipStyles.chip}
                aria-label={`Quitar ${chip.label}`}
                title={`Quitar ${chip.label}`}
                onClick={() => setFilters(chip.remove)}
              >
                {chip.label}
                <X size={12} aria-hidden="true" />
              </button>
            </li>
          ))}
          <li>
            <button type="button" className="btn-tesla ghost sm" onClick={() => setFilters(EMPTY_PRESENCE_FILTERS)}>
              <FilterX size={14} />
              Limpiar presencia
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
