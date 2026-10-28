import { useEffect, useState } from 'react';
import { preciosAPI } from '../services/api';

/**
 * The current USD rate (`venta`, the one pricing converts costs with), read
 * only when `enabled` (a USD cost or a USD per-unit offset needs it):
 * undefined while it loads, null when there is none.
 */
export function useUsdRate(enabled) {
  const [rate, setRate] = useState(undefined);
  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    setRate(undefined);
    preciosAPI
      .tipoCambioActual()
      .then((response) => {
        const venta = Number(response?.data?.venta);
        if (active) setRate(Number.isFinite(venta) && venta > 0 ? venta : null);
      })
      .catch(() => active && setRate(null));
    return () => {
      active = false;
    };
  }, [enabled]);
  return rate;
}
