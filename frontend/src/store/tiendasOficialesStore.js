import { create } from 'zustand';
import api from '../services/api';

// Official-store names, defined in the Admin panel (`ml_tiendas_oficiales`).
// Shared by every consumer: fetched once, `load(true)` forces a refetch.
let inflight = null;
let latestRequest = 0;

export const useTiendasOficialesStore = create((set, get) => ({
  tiendas: [],
  loaded: false,
  loading: false,

  load: (force = false) => {
    if (!force && (get().loaded || inflight)) return inflight || Promise.resolve();
    set({ loading: true });
    const request = ++latestRequest;
    // Only the newest request may write: an older one resolving late is dropped.
    const isLatest = () => request === latestRequest;
    const promise = Promise.resolve()
      .then(() => api.get('/tiendas-oficiales'))
      .then((response) => {
        const data = response?.data;
        if (isLatest()) set({ tiendas: Array.isArray(data) ? data : [], loaded: true, loading: false });
      })
      // Display data only: on failure every id falls back to "Tienda <id>".
      .catch(() => {
        if (isLatest()) set({ tiendas: [], loaded: true, loading: false });
      })
      .finally(() => {
        if (isLatest()) inflight = null;
      });
    inflight = promise;
    return promise;
  },
}));
