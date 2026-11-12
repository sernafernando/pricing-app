import { forwardRef } from 'react';
import { MoreVertical } from 'lucide-react';
import SearchInput from '../../SearchInput';
import { SegmentedControl } from '../../kit';
import styles from './PhoneLayout.module.css';

// The phone's views: the desktop's without Precios, whose price columns do not fit a card (mobile-metricas-pubml S2).
const PHONE_VISTA_OPTIONS = [
  { value: 'producto', label: 'Producto' },
  { value: 'publicacion', label: 'Publicaciones' },
  { value: 'agrupado', label: 'Agrupado' },
];

// The quick filters beside "Filtros": the same URL filters as the sheet's chips, one tap each.
const QUICK_FILTERS = [
  { label: 'Activas', key: 'estado', value: 'active' },
  { label: 'Pausadas', key: 'estado', value: 'paused' },
  { label: 'Markup negativo', key: 'markup_neg', value: '1', margin: true },
  { label: 'Sin stock ERP', key: 'stock', value: 'erp_sin_stock' },
  { label: 'Full', key: 'tipo', value: 'full' },
];

const isOn = (filters, { key, value }) =>
  Array.isArray(filters[key]) ? filters[key].includes(value) : filters[key] === value;

const toggled = (filters, { key, value }) => {
  const current = filters[key];
  if (!Array.isArray(current)) return { [key]: current === value ? '' : value };
  return { [key]: current.includes(value) ? current.filter((entry) => entry !== value) : [...current, value] };
};

/**
 * The phone layout's header (mobile-metricas-pubml S2): title and "⋯" (the bulk and export actions), the search, the
 * Vista switch and a sideways row of chips: "Filtros (n)", which opens the filters sheet, then the quick filters.
 */
const PhoneToolbar = forwardRef(function PhoneToolbar(
  { filters, setFilters, filterCount, showMarkupFilters, onOpenFilters, onOpenMenu, searchPlaceholder },
  searchRef,
) {
  const vista = filters.vista === 'precios' ? 'publicacion' : filters.vista;
  return (
    <header className={styles.header}>
      <div className={styles.titleRow}>
        <h1 className={styles.heading}>Publicaciones ML</h1>
        <button
          type="button"
          className={styles.iconButton}
          aria-label="Más acciones: pausar o activar, acciones masivas, exportar"
          onClick={onOpenMenu}
        >
          <MoreVertical size={20} aria-hidden="true" />
        </button>
      </div>
      <div className={styles.search}>
        <SearchInput
          ref={searchRef}
          value={filters.q}
          onChange={(value) => setFilters({ q: value })}
          debounce={400}
          placeholder={searchPlaceholder}
        />
      </div>
      <div className={styles.vista}>
        <SegmentedControl
          label="Vista"
          options={PHONE_VISTA_OPTIONS}
          value={vista}
          onChange={(value) => setFilters({ vista: value === 'publicacion' ? '' : value, mla: '' })}
        />
      </div>
      <div className={styles.chips} role="group" aria-label="Filtros rápidos">
        <button type="button" className={styles.chip} onClick={onOpenFilters}>
          Filtros
          {filterCount > 0 && <span className={styles.count}>{filterCount}</span>}
        </button>
        {QUICK_FILTERS.filter((chip) => !chip.margin || showMarkupFilters).map((chip) => (
          <button
            key={chip.label}
            type="button"
            className={styles.chip}
            aria-pressed={isOn(filters, chip)}
            onClick={() => setFilters(toggled(filters, chip))}
          >
            {chip.label}
          </button>
        ))}
      </div>
    </header>
  );
});

export default PhoneToolbar;
