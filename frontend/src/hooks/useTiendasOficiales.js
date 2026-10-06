import { useEffect } from 'react';
import { useTiendasOficialesStore } from '../store/tiendasOficialesStore';

/**
 * Official-store names defined in the Admin panel, keyed by ML's
 * `official_store_id`.
 *
 * - `getLabel(id)`: the store name; an id with no row renders as
 *   `Tienda <id>`; null/undefined stays null so the caller renders its own
 *   "Sin tienda".
 * - `tiendas`: every store (inactive too: their history still needs a name).
 * - `activas`: active stores ordered by `orden`, for pickers and chips.
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

  return { tiendas, activas, loading, getLabel, reload: () => load(true) };
}

export default useTiendasOficiales;
