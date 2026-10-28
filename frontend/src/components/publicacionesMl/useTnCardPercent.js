import { useEffect, useState } from 'react';
import api from '../../services/api';

/**
 * The Tienda Nube card surcharge (`porcentaje_tarjeta_tn`, a public config key) that Productos reads for its "transf."
 * hint (S3). Null until read, and when the read fails: PrecioTransfHint then draws nothing rather than a transfer
 * price that is not one. Unlike Productos no toast: a missing hint next to the TN price says enough here.
 * Read only when `enabled` (who sees Productos' prices).
 */
export default function useTnCardPercent(enabled = true) {
  const [percent, setPercent] = useState(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let current = true;
    api
      .get('/markups-tienda/config/porcentaje_tarjeta_tn')
      .then((response) => {
        if (current) setPercent(response.data?.valor ?? null);
      })
      .catch(() => {
        if (current) setPercent(null);
      });
    return () => {
      current = false;
    };
  }, [enabled]);
  return percent;
}
