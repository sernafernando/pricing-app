import { useEffect, useState } from 'react';
import { publicacionesMlAPI } from '../../services/api';

const IDLE = { status: 'idle', itemIds: [], sinProducto: 0, fueraDeCatalogo: 0, error: null };

/** The operator-facing reason the resolver gave no set (its own message for a 422 over the cap). */
function describeResolveError(error) {
  const message = error?.response?.data?.error?.message;
  if (error?.response?.status === 422 && message) return message;
  if (error?.response?.status === 503) return 'La consulta tardó demasiado: acotá los filtros o reintentá.';
  return 'No se pudieron resolver los productos del filtro.';
}

/**
 * The products a bulk pricing action acts on (`GET /ml-publications/view/product-ids` for `params`), asked again
 * when the filters change or after a bulk run (`reloadToken`). `status`: idle (not asked), loading, ready, error.
 * A stale answer never lands: a newer request aborts the older one.
 */
export default function useBulkProductSet(params, enabled, reloadToken = 0) {
  const [state, setState] = useState(IDLE);
  const key = JSON.stringify(params);

  useEffect(() => {
    if (!enabled) {
      setState(IDLE);
      return undefined;
    }
    const controller = new AbortController();
    setState({ ...IDLE, status: 'loading' });
    publicacionesMlAPI
      .productIds(JSON.parse(key), { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setState({
          status: 'ready',
          itemIds: response.data.item_ids,
          sinProducto: response.data.sin_producto,
          fueraDeCatalogo: response.data.fuera_de_catalogo ?? 0,
          error: null,
        });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({ ...IDLE, status: 'error', error: describeResolveError(error) });
      });
    return () => controller.abort();
  }, [key, enabled, reloadToken]);

  return state;
}
