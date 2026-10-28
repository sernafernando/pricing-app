import { useEffect, useRef, useState } from 'react';
import { FilterX, Tag, X } from 'lucide-react';
import { PROMO_TYPES } from '../../constants/promoTypes';
import { EMPTY_PROMO_FILTERS, PROMO_STATE_OPTIONS, activePromoChips } from './promoFilters';
import chipStyles from './ProductFilters.module.css';
import styles from './AuditFilters.module.css';

/**
 * The "Promos:" group of the Publicaciones ML filter card: Productos' promo filter (types, the state of those
 * types or of any promo, and "Precios mayoristas"), behind one button so the card does not grow a row. One
 * removable chip per active value and a control that clears them all stay in the row.
 *
 * @param {{filters: object, setFilters: (updates: object) => void, labelClassName?: string}} props
 */
export default function PromoFilters({ filters, setFilters, labelClassName }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);
  const chips = activePromoChips(filters);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', closeOutside);
    return () => document.removeEventListener('mousedown', closeOutside);
  }, [open]);

  const closeOnEscape = (event) => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  };

  const toggleType = (type) =>
    setFilters({
      promo_tipos: filters.promo_tipos.includes(type)
        ? filters.promo_tipos.filter((t) => t !== type)
        : [...filters.promo_tipos, type],
    });
  const label = chips.length > 0 ? `Filtros de promociones (${chips.length} activos)` : 'Filtros de promociones';

  return (
    <div className={chipStyles.group}>
      <span className={labelClassName}>Promos:</span>
      <div className={styles.anchor} ref={containerRef} onKeyDown={closeOnEscape}>
        <button
          type="button"
          className="btn-tesla outline sm"
          aria-expanded={open}
          aria-label={label}
          title={label}
          onClick={() => setOpen((was) => !was)}
        >
          <Tag size={14} aria-hidden="true" />
          Promos
          {chips.length > 0 && <span className={styles.count}>{chips.length}</span>}
        </button>
        {open && (
          <div className={styles.panel} role="group" aria-label="Filtros de promociones">
            <fieldset className={styles.section}>
              <legend className={styles.legend}>Tipo de promo</legend>
              <div className={styles.list}>
                {PROMO_TYPES.map(({ type, label: typeLabel }) => (
                  <label key={type} className={styles.option}>
                    <input
                      type="checkbox"
                      checked={filters.promo_tipos.includes(type)}
                      onChange={() => toggleType(type)}
                    />
                    {typeLabel}
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className={styles.section}>
              <legend className={styles.legend}>Estado</legend>
              <select
                aria-label="Estado de promo"
                className={styles.input}
                value={filters.promo_estado}
                onChange={(event) => setFilters({ promo_estado: event.target.value })}
              >
                {PROMO_STATE_OPTIONS.map(([value, text]) => (
                  <option key={value || 'disponible'} value={value}>
                    {text}
                  </option>
                ))}
              </select>
            </fieldset>
            <fieldset className={styles.section}>
              <legend className={styles.legend}>Precios mayoristas</legend>
              <select
                aria-label="Precios mayoristas"
                className={styles.input}
                value={filters.pxq}
                onChange={(event) => setFilters({ pxq: event.target.value })}
              >
                <option value="">Todos</option>
                <option value="con_pxq">Con precios mayoristas</option>
              </select>
            </fieldset>
          </div>
        )}
      </div>
      {chips.length > 0 && (
        <ul className={chipStyles.chips} aria-label="Filtros de promociones activos">
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
            <button type="button" className="btn-tesla ghost sm" onClick={() => setFilters(EMPTY_PROMO_FILTERS)}>
              <FilterX size={14} aria-hidden="true" />
              Limpiar promos
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
