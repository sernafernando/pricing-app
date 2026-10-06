/**
 * Official-store names live in the database (Admin > Tiendas Oficiales) and
 * are read through `useTiendasOficiales`. What stays here is the filter
 * sentinel and the chip builder shared by Ventas ML and Métricas ML.
 */

/** What the backend's `stores` param takes for an MLA published with no official store. */
export const STORE_NONE = 'sin_tienda';

/**
 * The "Tienda:" chips (Ventas ML, Métricas ML). Values are what the backend's
 * `stores` param takes (`mlp_official_store_id` as text, plus `sin_tienda`).
 *
 * - `activas`: active stores in display order; they keep their place even at
 *   zero sales.
 * - `counts` (Ventas ML facet): ANY other store it reports gets its own chip
 *   (ids ascending, before "Sin tienda"), so every sale counted in "Todas"
 *   sits under a chip that can be clicked. Omit it to offer active stores only.
 * - `selected`: stays a chip even if the facet drops it.
 * - `getLabel(id)`: the name to show (`Tienda <id>` for an unknown id).
 */
export function buildStoreChips({ activas = [], getLabel, counts = {}, selected = '' }) {
  const known = activas.map((tienda) => String(tienda.store_id));
  const others = new Set(
    Object.keys(counts || {}).filter((value) => value !== STORE_NONE && !known.includes(value)),
  );
  if (selected && selected !== STORE_NONE && !known.includes(selected)) others.add(selected);
  const extra = [...others].sort((a, b) => Number(a) - Number(b));
  const labels = { [STORE_NONE]: 'Sin tienda' };
  for (const value of [...known, ...extra]) labels[value] = getLabel(value);
  return { options: [...known, ...extra, STORE_NONE], labels };
}
