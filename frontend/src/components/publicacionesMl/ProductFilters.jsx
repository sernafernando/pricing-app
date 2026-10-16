import { FilterX, X } from 'lucide-react';
import ProductFiltersPanel from '../shared/ProductFiltersPanel';
import useProductFilterOptions from './useProductFilterOptions';
import { EMPTY_PRODUCT_FILTERS, activeProductChips, fromPanelValue, toPanelValue } from './productFilters';
import styles from './ProductFilters.module.css';

/**
 * The "Producto:" group of the Publicaciones ML filter card: Métricas ML's Marca / Categoría / Subcategoría / PM
 * pickers (the shared `ProductFiltersPanel`), one removable chip per active value and a control that clears the four.
 * The selection lives in the URL (`usePublicacionesMLFilters`), so every view (Producto, Publicaciones, Agrupado)
 * asks its endpoint with it.
 *
 * @param {{filters: object, setFilters: (updates: object) => void, labelClassName?: string}} props
 */
export default function ProductFilters({ filters, setFilters, labelClassName }) {
  const value = toPanelValue(filters);
  const options = useProductFilterOptions(value);
  const chips = activeProductChips(filters, options);

  return (
    <div className={styles.group}>
      <span className={labelClassName}>Producto:</span>
      <ProductFiltersPanel value={value} onChange={(next) => setFilters(fromPanelValue(next))} options={options} />
      {chips.length > 0 && (
        <ul className={styles.chips} aria-label="Filtros de producto activos">
          {chips.map((chip) => (
            <li key={chip.id}>
              <button
                type="button"
                className={styles.chip}
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
            <button type="button" className="btn-tesla ghost sm" onClick={() => setFilters(EMPTY_PRODUCT_FILTERS)}>
              <FilterX size={14} />
              Limpiar producto
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
