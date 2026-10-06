/**
 * Official-store names live in the database (Admin > Tiendas Oficiales) and
 * are read through `useTiendasOficiales`. What stays here is the filter
 * sentinel and the chip builder shared by Ventas ML and Métricas ML.
 */

/** What the backend's `stores` param takes for an MLA published with no official store. */
export const STORE_NONE = 'sin_tienda';

const byOrden = (a, b) => a.orden - b.orden || a.nombre.localeCompare(b.nombre);

/**
 * The options every store picker offers. Stores sharing a non-null `clave`
 * (e.g. the old and the new id of TP-Link) collapse into ONE option that
 * selects ALL their ids, inactive ones included (their history must stay in
 * the filter). Stores without a clave are one option per id. Only ACTIVE
 * stores are offered; a clave whose rows are all inactive is not offered.
 *
 * Returns `[{ value, ids, label }]` in `orden`; `value` is the ids joined by
 * `,` (what the backend's CSV params take), `label` the name of the group's
 * first active row.
 */
export function groupStores(tiendas = []) {
  const sorted = [...tiendas].sort(byOrden);
  const idsByClave = new Map();
  for (const tienda of sorted) {
    if (!tienda.clave) continue;
    idsByClave.set(tienda.clave, [...(idsByClave.get(tienda.clave) || []), String(tienda.store_id)]);
  }
  const grupos = [];
  const emitted = new Set();
  for (const tienda of sorted.filter((t) => t.activa)) {
    if (tienda.clave) {
      if (emitted.has(tienda.clave)) continue;
      emitted.add(tienda.clave);
      const ids = idsByClave.get(tienda.clave).sort((a, b) => Number(a) - Number(b));
      grupos.push({ value: ids.join(','), ids, label: tienda.nombre });
    } else {
      const id = String(tienda.store_id);
      grupos.push({ value: id, ids: [id], label: tienda.nombre });
    }
  }
  return grupos;
}

/**
 * Names a CSV selection of store ids: every group whose ids are ALL selected
 * by the group's name (so `2645,471846` reads "TP-Link"), the remaining ids
 * by their own name. Empty selection -> null.
 */
export function labelForIds(tiendas, getLabel, csv) {
  const ids = csv ? String(csv).split(',').map((id) => id.trim()).filter(Boolean) : [];
  if (ids.length === 0) return null;
  const grupos = groupStores(tiendas).filter((g) => g.ids.every((id) => ids.includes(id)));
  const sueltos = ids.filter((id) => !grupos.some((g) => g.ids.includes(id)));
  return [...grupos.map((g) => g.label), ...sueltos.map((id) => getLabel(id))].join(', ');
}

/**
 * The "Tienda:" chips (Ventas ML, Métricas ML). A chip's value is what the
 * backend's `stores` param takes: its ids as CSV (or `sin_tienda`).
 *
 * - `tiendas`: every store row (see `groupStores`).
 * - `counts` (Ventas ML facet, per id): a group chip's count is the SUM of
 *   its ids'. ANY other store the facet reports gets its own chip (ids
 *   ascending, before "Sin tienda"), so every sale counted in "Todas" sits
 *   under a chip that can be clicked (`facetExtras: false` offers the groups
 *   only, e.g. Métricas ML, whose options are the active stores).
 * - `selected`: CSV currently filtered. A group chip is active when ALL its
 *   ids are selected; an unknown selection stays a chip of its own.
 * - `getLabel(id)`: the name for an id outside the groups (`Tienda <id>`).
 *
 * Returns `{ options, labels, counts, activeValue }`.
 */
export function buildStoreChips({ tiendas = [], getLabel, counts = {}, selected = '', facetExtras = true }) {
  const grupos = groupStores(tiendas);
  const covered = new Set(grupos.flatMap((g) => g.ids));
  const selectedIds = selected ? selected.split(',').filter(Boolean) : [];

  const others = new Set(
    [...(facetExtras ? Object.keys(counts || {}) : []), ...selectedIds].filter((id) => id !== STORE_NONE && !covered.has(id)),
  );
  const extra = [...others].sort((a, b) => Number(a) - Number(b));

  const options = [...grupos.map((g) => g.value), ...extra, STORE_NONE];
  const labels = { [STORE_NONE]: 'Sin tienda' };
  const mergedCounts = { [STORE_NONE]: counts?.[STORE_NONE] ?? 0 };
  for (const grupo of grupos) {
    labels[grupo.value] = grupo.label;
    mergedCounts[grupo.value] = grupo.ids.reduce((sum, id) => sum + (counts?.[id] ?? 0), 0);
  }
  for (const id of extra) {
    labels[id] = getLabel(id);
    mergedCounts[id] = counts?.[id] ?? 0;
  }

  let activeValue = '';
  if (selectedIds.length > 0) {
    const selection = new Set(selectedIds);
    const match = grupos.find((g) => g.ids.every((id) => selection.has(id)));
    if (match) activeValue = match.value;
    else if (selection.size === 1 && options.includes(selected)) activeValue = selected;
    else {
      // A selection no chip stands for (e.g. a hand-edited list): keep it visible.
      activeValue = selected;
      options.splice(options.length - 1, 0, selected);
      labels[selected] = selectedIds.map((id) => getLabel(id)).join(', ');
      mergedCounts[selected] = 0;
    }
  }
  return { options, labels, counts: mergedCounts, activeValue };
}
