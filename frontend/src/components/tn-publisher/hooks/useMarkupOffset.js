/**
 * useMarkupOffset — the `porcentaje_tarjeta_tn` surcharge fetch, moved
 * verbatim out of the pre-decomposition `TnPublishModal.jsx`.
 */
import { useState, useEffect } from 'react';
import api from '../../../services/api';

export function useMarkupOffset({ isOpen, hasWebPrice }) {
  const [offsetPercent, setOffsetPercent] = useState(null);
  const [loadingOffset, setLoadingOffset] = useState(false);
  const [offsetError, setOffsetError] = useState(null);

  // Default surcharge — read from `porcentaje_tarjeta_tn` only on the
  // surcharge path (the manual-price path never uses an offset, so it would
  // be a pointless request). A failed read or a non-numeric value leaves
  // `offsetPercent` null on purpose: better to block the publish and say so
  // than to silently fall back to a number nobody configured.
  useEffect(() => {
    if (!isOpen || !hasWebPrice) return undefined;
    let cancelled = false;

    async function loadOffset() {
      setLoadingOffset(true);
      setOffsetError(null);
      try {
        const response = await api.get('/markups-tienda/config/porcentaje_tarjeta_tn');
        if (cancelled) return;
        const valor = Number(response.data?.valor);
        if (!Number.isFinite(valor)) {
          throw new Error('El porcentaje configurado no es un número válido');
        }
        setOffsetPercent(valor);
      } catch (err) {
        if (!cancelled) {
          setOffsetPercent(null);
          setOffsetError(
            err?.response?.data?.error?.message ||
              err?.message ||
              'No se pudo cargar el recargo configurado (porcentaje_tarjeta_tn)'
          );
        }
      } finally {
        if (!cancelled) setLoadingOffset(false);
      }
    }

    loadOffset();
    return () => {
      cancelled = true;
    };
  }, [isOpen, hasWebPrice]);

  return { offsetPercent, setOffsetPercent, loadingOffset, offsetError };
}
