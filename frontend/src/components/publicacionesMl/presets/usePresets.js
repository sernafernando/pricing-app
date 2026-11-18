import { useCallback, useEffect, useState } from 'react';
import { mlPublicationsPresetsAPI } from '../../../services/mlPublicationsPresets';

// The server's order: shared first, then by name.
const byKindAndName = (a, b) => Number(b.compartido) - Number(a.compartido) || a.nombre.localeCompare(b.nombre, 'es');

const NOT_LOADED = { items: [], loaded: false };

/**
 * The column presets of `vista` the user sees (pubml-columnas-presets S3): their personal ones and every shared one.
 * `create`, `update` and `remove` write to the server and, once it answers, to the list; they reject with the
 * server's error (409 a name already used, 403 a shared one without the permission) for the caller to show.
 * A failed load is an empty list: Predeterminado is always there.
 */
export default function usePresets(vista) {
  const [state, setState] = useState({ vista: null, ...NOT_LOADED });

  useEffect(() => {
    let cancelled = false;
    mlPublicationsPresetsAPI
      .list(vista)
      .then((items) => {
        if (!cancelled) setState({ vista, items: Array.isArray(items) ? [...items].sort(byKindAndName) : [], loaded: true });
      })
      .catch(() => {
        if (!cancelled) setState({ vista, items: [], loaded: true });
      });
    return () => {
      cancelled = true;
    };
  }, [vista]);

  const change = useCallback(
    (update) => setState((current) => (current.vista === vista ? { ...current, items: update(current.items).sort(byKindAndName) } : current)),
    [vista],
  );

  const create = useCallback(
    async (body) => {
      const preset = await mlPublicationsPresetsAPI.create({ ...body, vista });
      change((items) => [...items, preset]);
      return preset;
    },
    [vista, change],
  );

  const update = useCallback(
    async (id, body) => {
      const preset = await mlPublicationsPresetsAPI.update(id, body);
      change((items) => items.map((item) => (item.id === id ? { ...item, ...preset } : item)));
      return preset;
    },
    [change],
  );

  const remove = useCallback(
    async (id) => {
      await mlPublicationsPresetsAPI.remove(id);
      change((items) => items.filter((item) => item.id !== id));
    },
    [change],
  );

  const current = state.vista === vista ? state : NOT_LOADED;
  return { items: current.items, loaded: current.loaded, create, update, remove };
}
