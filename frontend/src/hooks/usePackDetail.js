import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api';

/**
 * usePackDetail — fetches the PACK-scoped breakdown (ventas-ml-rediseno
 * PR19, design D14, spec PANEL R22/R23) against
 * `GET /ml-ventas-ops/packs/{pack_id}` (BREAKDOWN R36). Mirrors
 * `SaleDetailPanel`'s own fetch discipline: a sequence guard so selecting
 * pack A then pack B fast cannot land A's response after B's, and a
 * defensive `errorKind` instead of throwing into the panel.
 */
export function usePackDetail(packId) {
  const [pack, setPack] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorKind, setErrorKind] = useState(null); // 'generic' | 'not_found' | null

  const latestRequestRef = useRef(0);

  const load = useCallback(async () => {
    if (packId === null || packId === undefined) return;
    const requestId = ++latestRequestRef.current;
    setLoading(true);
    setErrorKind(null);
    try {
      const { data } = await api.get(`/ml-ventas-ops/packs/${packId}`);
      if (requestId !== latestRequestRef.current) return;
      setPack(data || null);
    } catch (err) {
      if (requestId !== latestRequestRef.current) return;
      setErrorKind(err?.response?.status === 404 ? 'not_found' : 'generic');
      setPack(null);
    } finally {
      if (requestId === latestRequestRef.current) setLoading(false);
    }
  }, [packId]);

  useEffect(() => {
    load();
  }, [load]);

  return { pack, loading, errorKind };
}

export default usePackDetail;
