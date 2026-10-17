/** Display and request helpers of the sell-in screen. */

const AMOUNT = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const INT = new Intl.NumberFormat('es-AR');

/** `$ 1.000,00` for ARS, `USD 4.500,00` for USD (DESIGN.md number format). */
export function formatMonto(value, moneda) {
  if (value === null || value === undefined || value === '') return '—';
  const num = Number(value);
  if (Number.isNaN(num)) return '—';
  return `${moneda === 'USD' ? 'USD' : '$'} ${AMOUNT.format(num)}`;
}

export function formatNumero(value) {
  if (value === null || value === undefined || value === '') return '—';
  return AMOUNT.format(Number(value));
}

export const formatEntero = (value) => INT.format(value ?? 0);

/** The list/resumen query params: only what is set, `marcas` as CSV (exact match on the server). */
export function buildSellInParams({ aplica, q, marcas, moneda, estado, desde, hasta }) {
  const params = {
    aplica,
    q: q?.trim(),
    marcas: marcas?.length ? marcas.join(',') : '',
    moneda,
    estado,
    fecha_desde: desde,
    fecha_hasta: hasta,
  };
  return Object.fromEntries(Object.entries(params).filter(([, value]) => Boolean(value)));
}

/** Sum of the manual amounts, in cents so float noise never blocks a split that adds up. */
export function sumaManual(valores) {
  const cents = valores.reduce((acc, value) => acc + Math.round((Number(value) || 0) * 100), 0);
  return cents / 100;
}

export const FORMULA_LABELS = {
  proporcional: 'Reparto proporcional',
  por_unidad: 'Reparto igual por unidad',
  manual: 'Reparto manual',
};

/** The readable message of an API error (the repo's `{ error: { message } }` envelope, or a plain `detail`). */
export function apiMessage(err, fallback) {
  const data = err?.response?.data;
  const message = data?.error?.message ?? data?.detail;
  return typeof message === 'string' && message ? message : fallback;
}
