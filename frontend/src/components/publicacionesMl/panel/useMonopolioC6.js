import { useEffect, useState } from 'react';
import { promocionesAPI } from '../../../services/api';
import { monopolioFromSnapshotAndCriterios } from './monopolioC6';

/**
 * Loads criterios + latest catalog snapshot and returns a C6 opportunity (or null).
 */
export function useMonopolioC6(itemId) {
  const [loading, setLoading] = useState(Boolean(itemId));
  const [oportunidad, setOportunidad] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!itemId) {
      setLoading(false);
      setOportunidad(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const criteriosRes = await promocionesAPI.getHayMejoresCriterios(itemId);
        const criterios = criteriosRes.data;
        if (cancelled) return;
        if (!criterios?.c6_activo) {
          setOportunidad(null);
          return;
        }
        let snapshot = null;
        try {
          const snapRes = await promocionesAPI.getCompetenciaCatalogo(itemId);
          snapshot = snapRes.data;
        } catch {
          if (!cancelled) {
            setOportunidad(null);
            setError('No se pudo cargar el ranking de catálogo para monopolio');
          }
          return;
        }
        if (cancelled) return;
        setOportunidad(monopolioFromSnapshotAndCriterios(itemId, snapshot, criterios));
      } catch {
        if (!cancelled) {
          setOportunidad(null);
          setError('No se pudo evaluar monopolio');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [itemId]);

  return { loading, oportunidad, error };
}
