import { useEffect, useRef, useState } from 'react';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';

const EMPTY = {};

/**
 * Fetches prearmadas availability stats for a batch of item_ids.
 *
 * @param {number[]} itemIds - List of item_ids to query.
 * @param {Object} [options]
 * @param {boolean} [options.forceRefresh=false] - Bypass Redis cache.
 * @returns {{ statsById: Object, loading: boolean, error: any }}
 *   statsById is keyed by item_id (string from API): { exact: number, upgrade: number }
 */
export function usePrearmadasStats(itemIds, { forceRefresh = false } = {}) {
  const [statsById, setStatsById] = useState(EMPTY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const { tienePermiso } = usePermisos();
  const lastKeyRef = useRef(null);

  useEffect(() => {
    if (!tienePermiso('produccion.ver_prearmadas_stats')) {
      setStatsById(EMPTY);
      return;
    }

    if (!itemIds || itemIds.length === 0) {
      setStatsById(EMPTY);
      return;
    }

    // Build a stable key from the sorted deduplicated ids to avoid redundant requests.
    const dedupedIds = [...new Set(itemIds)].sort((a, b) => a - b);
    const key = dedupedIds.join(',');

    if (key === lastKeyRef.current && !forceRefresh) return;
    lastKeyRef.current = key;

    let cancelled = false;
    setLoading(true);
    setError(null);

    const params = forceRefresh ? { params: { force_refresh: 1 } } : undefined;

    api
      .post(
        '/prearmados/stats/batch',
        { items: dedupedIds.map((id) => ({ item_id: id })) },
        params,
      )
      .then(({ data }) => {
        if (!cancelled) setStatsById(data.stats || EMPTY);
      })
      .catch((err) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [itemIds, forceRefresh, tienePermiso]);

  return { statsById, loading, error };
}

export default usePrearmadasStats;
