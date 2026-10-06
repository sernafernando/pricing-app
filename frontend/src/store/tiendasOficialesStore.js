import { create } from 'zustand';
import api from '../services/api';

// Official-store names, defined in the Admin panel (`ml_tiendas_oficiales`).
// Shared by every consumer: fetched once, `load(true)` forces a refetch.
let inflight = null;

export const useTiendasOficialesStore = create((set, get) => ({
  tiendas: [],
  loaded: false,
  loading: false,

  load: (force = false) => {
    if (!force && (get().loaded || inflight)) return inflight || Promise.resolve();
    set({ loading: true });
    inflight = api
      .get('/tiendas-oficiales')
      .then(({ data }) => set({ tiendas: Array.isArray(data) ? data : [], loaded: true, loading: false }))
      // Display data only: on failure every id falls back to "Tienda <id>".
      .catch(() => set({ tiendas: [], loaded: true, loading: false }))
      .finally(() => {
        inflight = null;
      });
    return inflight;
  },
}));
