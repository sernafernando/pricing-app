import { PERMISO_TPLINK_SOLO } from '../../contexts/ThemeContext';

/**
 * Ventas ML in TP mode (metricas-ml-tplink-mode P7): a `tplink.solo` user
 * sees only the TP store group, costed at the TP cost, and never a Gauss
 * figure. The backend enforces it; the screen just shows what it gets.
 *
 * Read from the explicit permission list, the same way ThemeContext does:
 * the code is opt-in, so a SUPERADMIN is in TP mode only when granted it.
 */
export function isTpSolo(permisos) {
  return Array.isArray(permisos) && permisos.includes(PERMISO_TPLINK_SOLO);
}

/**
 * The "Tienda:" chips (`buildStoreChips`) narrowed to the stores the facet
 * returned. The TP facet only carries the TP group, so a Gauss store or
 * "Sin tienda" chip would be a filter the backend answers with nothing.
 * The active chip stays, so the filter in use is still visible.
 */
export function onlyFacetStoreChips(chips, facetCounts) {
  const returned = new Set(Object.keys(facetCounts || {}));
  const options = chips.options.filter(
    (option) => option === chips.activeValue || option.split(',').some((id) => returned.has(id)),
  );
  return { ...chips, options };
}
