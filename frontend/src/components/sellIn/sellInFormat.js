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

const PERCENT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 4 });

/** A purchase's percentage as typed: `2,5 %`, up to the column's 4 decimals. */
export function formatPorcentaje(value) {
  if (value === null || value === undefined || value === '') return '—';
  const num = Number(value);
  return Number.isNaN(num) ? '—' : `${PERCENT.format(num)} %`;
}

const soloLoPuesto = (params) => Object.fromEntries(Object.entries(params).filter(([, value]) => Boolean(value)));

/**
 * The purchases' list/resumen query params: only what is set, `marcas` as CSV (exact match on the server), the
 * picked product and supplier by id.
 */
export function buildSellInParams({ aplica, q, marcas, moneda, estado, desde, hasta, producto, proveedor }) {
  return soloLoPuesto({
    aplica,
    ...buildBonosParams({ q, marcas, moneda, estado, desde, hasta }),
    item_id: producto?.item_id,
    proveedor_id: proveedor?.id,
  });
}

/**
 * The brand bonuses' list query params from the same filters: the ones a bonus has. Not `aplica` (a bonus has no
 * "aplica"), nor the product or supplier (a bonus reaches a brand, a category, models or an operation, not a
 * supplier). The dates keep the bonuses whose own range overlaps the period.
 */
export function buildBonosParams({ q, marcas, moneda, estado, desde, hasta }) {
  return soloLoPuesto({
    q: q?.trim(),
    marcas: marcas?.length ? marcas.join(',') : '',
    moneda,
    estado,
    fecha_desde: desde,
    fecha_hasta: hasta,
  });
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
