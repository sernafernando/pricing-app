/**
 * formatMoney — shared es-AR money display formatter (defect 2,
 * tn-publisher money path). Two decimals, thousands separator `.`,
 * decimal separator `,`, `$ ` prefix — e.g. `formatMoney(38762.5)` ->
 * `"$ 38.762,50"`.
 *
 * DISPLAY ONLY. Never use this to derive a value that gets submitted to
 * the backend — the publish payload must keep sending the raw
 * unformatted value it sends today (see `usePublishSubmit`'s `numOrNull`).
 * Rounding/formatting here is cosmetic and must never leak into the wire
 * value.
 */
export function formatMoney(value) {
  if (value === null || value === undefined || value === '') return null;
  const num = Number(value);
  if (Number.isNaN(num)) return null;
  return `$ ${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
