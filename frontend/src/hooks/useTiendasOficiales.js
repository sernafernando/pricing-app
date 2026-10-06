import { useEffect } from 'react';
import { useTiendasOficialesStore } from '../store/tiendasOficialesStore';
import { groupStores, labelForIds, labelsForIds, groupValueForSelection } from '../constants/tiendasOficiales';

/**
 * Official-store names defined in the Admin panel, keyed by ML's
 * `official_store_id`.
 *
 * - `getLabel(id)`: the store name; an id with no row renders as
 *   `Tienda <id>`; null/undefined stays null so the caller renders its own
 *   "Sin tienda".
 * - `getLabelForIds(csv)`: the name of a CSV selection (a whole clave group by
 *   its name, the rest by their own).
 * - `getLabelsForIds(csv)`: the same as a list (one entry per group/store).
 * - `getGroupValue(csv)`: the picker option a selection maps to (a legacy
 *   single id of a grouped store -> the group's option).
 * - `tiendas`: every store (inactive too: their history still needs a name).
 * - `activas`: active stores ordered by `orden`.
 * - `grupos`: the picker options (see `groupStores`): stores sharing a `clave`
 *   collapse into one option that selects every id of the clave.
 */
export function useTiendasOficiales() {
  const tiendas = useTiendasOficialesStore((state) => state.tiendas);
  const loading = useTiendasOficialesStore((state) => state.loading);
  const load = useTiendasOficialesStore((state) => state.load);

  useEffect(() => {
    load();
  }, [load]);

  const getLabel = (id) => {
    if (id === null || id === undefined) return null;
    const tienda = tiendas.find((t) => String(t.store_id) === String(id));
    return tienda ? tienda.nombre : `Tienda ${id}`;
  };

  const activas = tiendas.filter((t) => t.activa).sort((a, b) => a.orden - b.orden || a.nombre.localeCompare(b.nombre));

  const getLabelForIds = (csv) => labelForIds(tiendas, getLabel, csv);
  const getLabelsForIds = (csv) => labelsForIds(tiendas, getLabel, csv);
  const getGroupValue = (csv) => groupValueForSelection(tiendas, csv);

  return { tiendas, activas, getLabelForIds, getLabelsForIds, getGroupValue, grupos: groupStores(tiendas), loading, getLabel, reload: () => load(true) };
}

export default useTiendasOficiales;
