/**
 * Formatting and colour semantics for the Métricas ML board
 * (ODD `metricas-ml-tablero` T4). Money goes through `ventasMlTone.js`
 * (`formatSignedMoney`, `markupTone`) so both screens read the same; this
 * module holds what is new here: deltas, ageing, publication descriptors and
 * the sparkline helpers.
 */

const INT = new Intl.NumberFormat('es-AR');
const ONE_DECIMAL = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const BUSINESS_TZ = 'America/Argentina/Buenos_Aires';

const isNumber = (value) => value !== null && value !== undefined && Number.isFinite(Number(value));

export function formatUnits(value) {
  return isNumber(value) ? INT.format(Number(value)) : '—';
}

export function formatPct(value) {
  return isNumber(value) ? `${ONE_DECIMAL.format(Number(value))}%` : '—';
}

function arrowed(value, suffix) {
  if (!isNumber(value)) return '—';
  const n = Number(value);
  const text = ONE_DECIMAL.format(Math.abs(n));
  if (n > 0) return `▲ +${text}${suffix}`;
  if (n < 0) return `▼ -${text}${suffix}`;
  return `– ${text}${suffix}`;
}

/** Markup change in percentage POINTS: `▲ +2,1 pp`. */
export const formatDeltaPp = (value) => arrowed(value, ' pp');

/** Relative change of a quantity: `▲ +12,4%`. */
export const formatDeltaPct = (value) => arrowed(value, '%');

export function deltaTone(value) {
  if (!isNumber(value)) return null;
  const n = Number(value);
  if (n > 0) return 'up';
  if (n < 0) return 'down';
  return 'flat';
}

/** Ageing: up to 30 days healthy, up to 60 amber, beyond that red (the
 * "Ageing > 60d" alert). */
export function ageingTone(days) {
  if (!isNumber(days)) return null;
  if (days <= 30) return 'good';
  if (days <= 60) return 'low';
  return 'negative';
}

export function formatAgeing(days) {
  return isNumber(days) ? `${INT.format(days)} d` : '—';
}

const LISTING_LABELS = { clasica: 'Clásica', premium: 'Premium' };
const STATUS_LABELS = {
  active: 'Activa',
  paused: 'Pausada',
  closed: 'Cerrada',
  under_review: 'En revisión',
};

export const PUB_STATUS_OPTIONS = ['active', 'paused', 'closed'];
export const PUB_STATUS_LABELS = STATUS_LABELS;
export const PUB_TYPE_OPTIONS = ['clasica', 'premium', 'catalogo', 'full'];
export const PUB_TYPE_LABELS = { clasica: 'Clásica', premium: 'Premium', catalogo: 'Catálogo', full: 'Full' };

/** The row's ERP stock buckets (`STOCK_BUCKETS` in the board service):
 * "Sin dato" = the product has no stock in the ERP mirror. */
export const STOCK_OPTIONS = ['con_stock', 'sin_stock', 'sin_dato'];
export const STOCK_LABELS = { con_stock: 'Con stock', sin_stock: 'Sin stock', sin_dato: 'Sin dato' };

/** The ageing KPI's buckets (`AGEING_BUCKETS` in the board service), with
 * the same tones as the Ageing column (`ageingTone`). */
export const AGEING_OPTIONS = ['up_to_30', 'from_31_to_60', 'over_60'];
export const AGEING_LABELS = { up_to_30: 'Hasta 30 d', from_31_to_60: '31 a 60 d', over_60: 'Más de 60 d' };
export const AGEING_BUCKET_TONES = { up_to_30: 'good', from_31_to_60: 'low', over_60: 'negative' };

/** `Clásica · Full · Activa` -- what the design writes next to an MLA. */
export function publicationDescriptor(pub) {
  const parts = [];
  if (pub.listing_type) parts.push(LISTING_LABELS[pub.listing_type] || pub.listing_type);
  if (pub.is_catalog) parts.push('Catálogo');
  if (pub.is_full) parts.push('Full');
  parts.push(pub.status ? STATUS_LABELS[pub.status] || pub.status : 'Sin estado');
  return parts.join(' · ');
}

/** A daily series summed into weeks, the LAST week ending on the last day
 * (a partial week, if any, is the first one). Sums of units are exact; a
 * sparkline of 90 daily points is mostly noise. */
export function weeklySums(daily) {
  const weeks = [];
  for (let end = daily.length; end > 0; end -= 7) {
    const start = Math.max(0, end - 7);
    weeks.unshift(daily.slice(start, end).reduce((acc, n) => acc + (n || 0), 0));
  }
  return weeks;
}

const DAY_MONTH_TIME = new Intl.DateTimeFormat('es-AR', {
  timeZone: BUSINESS_TZ,
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const ISO_DAY = new Intl.DateTimeFormat('en-CA', { timeZone: BUSINESS_TZ });

function businessDayNumber(date) {
  return Math.round(Date.parse(`${ISO_DAY.format(date)}T00:00:00Z`) / 86400000);
}

/** `{ when: '29/09 18:40', ago: 'hace 1 día' }` in Buenos Aires time. */
export function formatLastSale(iso, now = new Date()) {
  if (!iso) return { when: '—', ago: 'sin ventas' };
  const date = new Date(iso);
  const parts = Object.fromEntries(DAY_MONTH_TIME.formatToParts(date).map((p) => [p.type, p.value]));
  const days = businessDayNumber(now) - businessDayNumber(date);
  const ago = days <= 0 ? 'hoy' : days === 1 ? 'hace 1 día' : `hace ${INT.format(days)} días`;
  const pad = (text) => String(text).padStart(2, '0');
  return { when: `${pad(parts.day)}/${pad(parts.month)} ${pad(parts.hour)}:${pad(parts.minute)}`, ago };
}
