import { useState } from 'react';
import { recalcularCuotasPreference, setRecalcularCuotasPreference } from '../pricing/priceWrites';

/**
 * Productos' "Auto-recalcular" cuotas (S12f2): the same per-browser preference (default on) Productos and Tienda
 * flip, so the three screens share it. Price writes read it when they save (`priceWrites.recalcularCuotas`), after
 * the product's own setting.
 */
export default function useRecalcularCuotasAuto() {
  const [enabled, setEnabled] = useState(recalcularCuotasPreference);
  const toggle = () => {
    setRecalcularCuotasPreference(!enabled);
    setEnabled(!enabled);
  };
  return { enabled, toggle };
}
