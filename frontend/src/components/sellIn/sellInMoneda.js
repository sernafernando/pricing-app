/**
 * Currency display helpers shared by the sell-in screens (#2381 precedent): an amount is shown as loaded, in its own
 * currency, and its conversion goes below it as `<converted> a TC <rate>`, so USD costs stay visible in USD (owner L35).
 */

// A unit price can be a fraction of a cent: up to 5 decimals (the stored precision), at least 2.
const PRECIO = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 5 });
const MONTO = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const TC = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 });

/** `USD 0,00971`: a unit price with its currency code. */
export const precio = (valor, moneda) => `${moneda} ${PRECIO.format(Number(valor))}`;

/** `<texto> a TC 1.560`: a converted value and the rate it was converted at. */
export const aTipoCambio = (texto, tipoCambio) => `${texto} a TC ${TC.format(Number(tipoCambio))}`;

/**
 * An ARS amount's USD equivalent at the purchase's rate (`USD 250,62 a TC 1.570`), or null when the amount is not in
 * ARS, has no positive rate or is empty: a USD amount is already in USD.
 */
export function equivalenteUsd(monto, moneda, tipoCambio) {
  const tc = Number(tipoCambio);
  if (moneda !== 'ARS' || !(tc > 0) || monto === null || monto === undefined || monto === '') return null;
  const valor = Number(monto);
  if (Number.isNaN(valor)) return null;
  return aTipoCambio(`USD ${MONTO.format(valor / tc)}`, tc);
}
