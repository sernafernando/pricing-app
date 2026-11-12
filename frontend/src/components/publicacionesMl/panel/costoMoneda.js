import { amount } from './format';

const isBlank = (value) => value === null || value === undefined;

/** True when the figure is in a currency other than pesos (S10: a USD cost reads in USD). */
export const isForeign = (moneda) => Boolean(moneda) && moneda !== 'ARS';

/**
 * The breakdown's unit cost in the cost's own currency (S10): `{ monto, moneda }`, USD for a USD cost, else the
 * pesos (`costo_ars`, also what an older backend without `moneda_costo` sends).
 */
export function costoEnMoneda(breakdown) {
  if (isForeign(breakdown?.moneda_costo) && !isBlank(breakdown.costo)) {
    return { monto: breakdown.costo, moneda: breakdown.moneda_costo };
  }
  return { monto: breakdown?.costo_ars, moneda: 'ARS' };
}

/** `USD 17,04` for a foreign currency, the screen's own pesos format (`format`) for ARS. */
export const formatMoneda = (monto, moneda, format = amount) =>
  isForeign(moneda) ? `${moneda} ${amount(monto)}` : format(monto);
