import { useEffect, useState } from 'react';
import { publicacionesMlAPI } from '../../services/api';

/** What to tell the operator when the variations cannot be loaded. */
export function describeVariationsError(error) {
  const status = error?.response?.status;
  if (status === 404) return 'La publicación ya no existe.';
  if (status === 422) return 'El identificador de la publicación no es válido.';
  if (status === 403) return 'No tenés permiso para ver las variaciones.';
  if (status === 503) return 'La consulta tardó demasiado. Reintentá en unos segundos.';
  return 'No se pudieron cargar las variaciones.';
}

/**
 * Loads the variations of `itemId` when it mounts. Mounted only while the row is
 * expanded, so a collapsed publication costs no request. `attempt` re-runs it.
 */
export function useVariations(itemId, attempt) {
  const [state, setState] = useState({ status: 'loading', variations: [], error: null });
  useEffect(() => {
    let current = true;
    setState({ status: 'loading', variations: [], error: null });
    publicacionesMlAPI
      .variations(itemId)
      .then((response) => {
        if (current) setState({ status: 'ready', variations: response.data?.variations ?? [], error: null });
      })
      .catch((error) => {
        if (current) setState({ status: 'error', variations: [], error });
      });
    return () => {
      current = false;
    };
  }, [itemId, attempt]);
  return state;
}
