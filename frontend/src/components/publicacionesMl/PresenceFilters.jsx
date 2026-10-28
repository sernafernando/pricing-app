import { useEffect, useRef, useState } from 'react';
import { FilterX, SlidersHorizontal, X } from 'lucide-react';
import { EMPTY_PRESENCE_FILTERS, MARKUP_SIGN_FILTERS, PRESENCE_FILTERS, activePresenceChips } from './presenceFilters';
import chipStyles from './ProductFilters.module.css';
import styles from './PresenceFilters.module.css';

/**
 * The "Presencia:" group of the Publicaciones ML filter card: Productos' "Filtros de Presencia" (rebate, mejor
 * oferta, web transferencia, Tienda Nube, out of cards) plus its Precio and Productos Nuevos selects, each a
 * Todos / con / sin select as in Productos. Like Productos keeps them behind "Filtros Avanzados", they sit in a
 * panel behind one button, so the filter card does not grow a row (the list's table must keep its header on screen at 1366x768). One removable chip per active
 * toggle and a control that clears them all stay in the row. The values live in the URL
 * (`usePublicacionesMLFilters`), so every view asks its endpoint with them.
 *
 * With `canSeeMargin` the panel also offers Productos' four markup selects.
 *
 * @param {{filters: object, setFilters: (updates: object) => void, labelClassName?: string, canSeeMargin?: boolean}} props
 */
export default function PresenceFilters({ filters, setFilters, labelClassName, canSeeMargin = false }) {
  const [open, setOpen] = useState(false);
  const offered = canSeeMargin ? [...PRESENCE_FILTERS, ...MARKUP_SIGN_FILTERS] : PRESENCE_FILTERS;
  const containerRef = useRef(null);
  const chips = activePresenceChips(filters);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', closeOutside);
    return () => document.removeEventListener('mousedown', closeOutside);
  }, [open]);

  // Escape closes the panel only while focus is inside it: the page's own Escape (closing the detail) stays its own.
  const closeOnEscape = (event) => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  };

  const label = chips.length > 0 ? `Filtros de presencia (${chips.length} activos)` : 'Filtros de presencia';

  return (
    <div className={chipStyles.group}>
      <span className={labelClassName}>Presencia:</span>
      <div className={styles.anchor} ref={containerRef} onKeyDown={closeOnEscape}>
        <button
          type="button"
          className="btn-tesla outline sm"
          data-filter="presencia"
          aria-expanded={open}
          aria-label={label}
          title={label}
          onClick={() => setOpen((was) => !was)}
        >
          <SlidersHorizontal size={14} aria-hidden="true" />
          Filtros
          {chips.length > 0 && <span className={styles.count}>{chips.length}</span>}
        </button>
        {open && (
          <div className={styles.panel} role="group" aria-label="Filtros de presencia">
            {offered.map(({ key, icon: Icon, name, options }) => (
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
                  {options.map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        )}
      </div>
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
              <FilterX size={14} aria-hidden="true" />
              Limpiar presencia
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
