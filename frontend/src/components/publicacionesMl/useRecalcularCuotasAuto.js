import { useEffect, useState } from 'react';
import {
  RECALCULAR_CUOTAS_KEY,
  recalcularCuotasPreference,
  setRecalcularCuotasPreference,
} from '../pricing/priceWrites';

/**
 * Productos' "Auto-recalcular" cuotas (S12f2): the same per-browser preference (default on) Productos and Tienda
 * flip, so the three screens share it. Price writes read it when they save (`priceWrites.recalcularCuotas`), after
 * the product's own setting. A change made in another tab shows here too, and a toggle flips the live value.
 */
export default function useRecalcularCuotasAuto() {
  const [enabled, setEnabled] = useState(recalcularCuotasPreference);
  useEffect(() => {
    const onStorage = (event) => {
      if (event.key === RECALCULAR_CUOTAS_KEY || event.key === null) setEnabled(recalcularCuotasPreference());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);
  const toggle = () => {
    const next = !recalcularCuotasPreference();
    setRecalcularCuotasPreference(next);
    setEnabled(next);
  };
  return { enabled, toggle };
}
