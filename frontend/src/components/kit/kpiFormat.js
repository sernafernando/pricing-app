/**
 * Number formatting shared by the Ventas ML KPI strips (`KpiStrip` and the
 * TP-only `ventasMl/KpiStripTP`), so both read every figure the same way.
 */

const INT_FORMAT = new Intl.NumberFormat('es-AR');
const MONEY_FORMAT = new Intl.NumberFormat('es-AR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const PCT_FORMAT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 });

/** A count; a missing one reads 0 (counts, unlike money, have no unknown). */
export function formatInt(value) {
  return INT_FORMAT.format(value ?? 0);
}

/** A percentage; `null`/`undefined` read "—", never "0%". */
export function formatPct(value) {
  if (value === null || value === undefined) return '—';
  return `${PCT_FORMAT.format(Number(value))}%`;
}

/** Non-ARS billing, one entry per currency: a different unit, never "more pesos". */
export function formatOtherCurrencies(grossBilledOther) {
  const entries = Object.entries(grossBilledOther || {});
  if (entries.length === 0) return null;
  return entries.map(([currency, amount]) => `${MONEY_FORMAT.format(Number(amount))} ${currency}`).join(' · ');
}
