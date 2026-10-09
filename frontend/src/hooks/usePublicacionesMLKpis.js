import { useEffect, useState } from 'react';
import { publicacionesMlAPI } from '../services/api';

/**
 * The KPI strip's data (publicaciones-ml-vista P12b): `GET /ml-publications/view/kpis` for `params`, asked again
 * only when they change (or on `reload`). It does not know the rows: a period change moves this request alone.
 * A request that is no longer the latest is aborted, and the last good figures stay while the next ones load.
 */
export function usePublicacionesMLKpis(params, enabled) {
  const [state, setState] = useState({ data: null, loading: enabled, error: null });
  const [reloadToken, setReloadToken] = useState(0);
  const key = JSON.stringify(params);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    setState((current) => ({ ...current, loading: true, error: null }));
    publicacionesMlAPI
      .kpis(JSON.parse(key), { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) setState({ data: response.data, loading: false, error: null });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState((current) => ({ ...current, loading: false, error }));
      });
    return () => controller.abort();
  }, [key, enabled, reloadToken]);

  return { ...state, reload: () => setReloadToken((token) => token + 1) };
}
