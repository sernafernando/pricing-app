import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';

const PERM = 'produccion.ver_prearmadas_stats';

/**
 * Fetches the paginated list of armado prearmadas from
 * GET /prearmados/stats/armadas.
 *
 * @param {Object} params
 * @param {string}  params.eanBase   - Optional ean_base substring filter.
 * @param {number}  params.page      - Current page (1-based).
 * @param {number}  params.pageSize  - Page size.
 * @returns {{ items, total, loading, error, refetch }}
 */
export function usePrearmadasArmadas({ eanBase = '', page = 1, pageSize = 50 } = {}) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const { tienePermiso } = usePermisos();
  const abortRef = useRef(null);

  const fetchData = useCallback(() => {
    if (!tienePermiso(PERM)) {
      setItems([]);
      setTotal(0);
      return;
    }

    // Cancel in-flight request if any
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    const queryParams = { page, page_size: pageSize };
    if (eanBase && eanBase.trim()) {
      queryParams.ean_base = eanBase.trim();
    }

    api
      .get('/prearmados/stats/armadas', {
        params: queryParams,
        signal: controller.signal,
      })
      .then(({ data }) => {
        setItems(data.items || []);
        setTotal(data.total || 0);
      })
      .catch((err) => {
        if (err.name !== 'CanceledError' && err.code !== 'ERR_CANCELED') {
          setError(err);
        }
      })
      .finally(() => {
        setLoading(false);
      });
  }, [eanBase, page, pageSize, tienePermiso]);

  useEffect(() => {
    fetchData();
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, [fetchData]);

  return { items, total, loading, error, refetch: fetchData };
}

export default usePrearmadasArmadas;
