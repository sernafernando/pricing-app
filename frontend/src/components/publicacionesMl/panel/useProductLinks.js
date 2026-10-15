import { useCallback, useEffect, useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';

/**
 * The link units of one publication (`GET /ml-publications/items/{id}/product-links`),
 * loaded only when `enabled` (the caller may edit the links). Unlike the
 * detail's `links`, it lists every live unit -- also the ones the automatic
 * rule never evaluated -- with the conflict candidates of each.
 *
 * @returns {{ status: 'idle'|'loading'|'ready'|'error', units: Array, reload: () => void }}
 */
export function useProductLinks(itemId, enabled) {
  const [state, setState] = useState({ status: 'idle', units: [], key: null });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled || !itemId) return undefined;
    let alive = true;
    setState((prev) => ({ status: 'loading', units: prev.key === itemId ? prev.units : [], key: itemId }));
    publicacionesMlAPI.productLinks(itemId).then(
      (response) => alive && setState({ status: 'ready', units: response?.data?.units ?? [], key: itemId }),
      () => alive && setState((prev) => ({ ...prev, status: 'error' })),
    );
    return () => {
      alive = false;
    };
  }, [itemId, enabled, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  if (!enabled) return { status: 'idle', units: [], reload };
  return { status: state.status, units: state.key === itemId ? state.units : [], reload };
}
