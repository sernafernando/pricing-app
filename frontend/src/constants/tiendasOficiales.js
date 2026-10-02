/**
 * Display metadata for MercadoLibre official stores, keyed by
 * `mlp_official_store_id`.
 *
 * Single source of truth: extracted from the official-store filter
 * `<select>` in `Productos.jsx`, now also consumed by `TreeNode.jsx`'s
 * per-MLA store badge (promos-catalog-prices-and-official-store, slice A).
 * An id outside this map is unknown, not invalid — callers render the raw
 * id rather than hiding it.
 */
export const TIENDAS_OFICIALES = {
  57997: { label: 'Gauss', emoji: '🏢', title: undefined },
  2645: { label: 'TP-Link', emoji: '📡', title: 'TP-Link' },
  144: { label: 'Forza/Verbatim', emoji: '⚡', title: 'Forza, Verbatim' },
  191942: { label: 'Multi-marca', emoji: '🎯', title: 'Epson, Forza, Logitech, MGN, Razer' },
};

/**
 * Display order for the filter `<select>`. Integer-like object keys are
 * NOT iterated in insertion order by JS (they sort numerically ascending),
 * so `Object.entries(TIENDAS_OFICIALES)` cannot be trusted for UI order —
 * this explicit list is the source of truth for that.
 */
export const TIENDAS_OFICIALES_ORDER = [57997, 2645, 144, 191942];

/**
 * Returns the display label for a given official store id, or the raw id
 * (stringified) when unknown. `null`/`undefined` -> `null` (caller decides
 * how to render "sin tienda").
 */
export function getTiendaOficialLabel(officialStoreId) {
  if (officialStoreId === null || officialStoreId === undefined) return null;
  const entry = TIENDAS_OFICIALES[officialStoreId];
  return entry ? entry.label : String(officialStoreId);
}

/**
 * ODD `metricas-ml-tablero` T1: the "Tienda:" filter chips on Ventas ML and
 * Métricas ML. Values are what the backend's `stores` param takes
 * (`mlp_official_store_id` as text, plus the `sin_tienda` sentinel for an
 * MLA published with no official store). Labels are the product's names for
 * the stores on these screens, deliberately not `TIENDAS_OFICIALES` labels.
 */
export const STORE_NONE = 'sin_tienda';
export const STORE_FILTER_OPTIONS = ['57997', '2645', '144', '191942', STORE_NONE];
export const STORE_FILTER_LABELS = {
  57997: 'Gauss',
  2645: 'TP-Link Oficial',
  144: 'Forza/Verbatim',
  191942: 'Multimarca',
  [STORE_NONE]: 'Sin tienda',
};

/**
 * The "Tienda:" chips for the facet the backend returned. The known stores
 * keep their place and label (even at zero); ANY other store the facet
 * reports gets its own "Tienda <id>" chip (ids ascending, before
 * "Sin tienda"), so every sale counted in "Todas" sits under a chip that can
 * be clicked. The selected store stays a chip even if the facet drops it.
 */
export function storeFilterChips(counts = {}, selected = '') {
  const known = STORE_FILTER_OPTIONS.filter((value) => value !== STORE_NONE);
  const others = new Set(
    Object.keys(counts || {}).filter((value) => value !== STORE_NONE && !known.includes(value)),
  );
  if (selected && selected !== STORE_NONE && !known.includes(selected)) others.add(selected);
  const extra = [...others].sort((a, b) => Number(a) - Number(b));
  const labels = { ...STORE_FILTER_LABELS };
  for (const value of extra) labels[value] = `Tienda ${value}`;
  return { options: [...known, ...extra, STORE_NONE], labels };
}

export default TIENDAS_OFICIALES;
