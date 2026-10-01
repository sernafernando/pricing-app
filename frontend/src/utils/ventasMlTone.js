/**
 * Color semantics for the Ventas ML screen: which way a number points, and
 * what tone it is painted in. Kept apart from `ventasMlFormat.js` so the
 * "is this good or bad" decisions live in one small, tested place.
 *
 * MARKUP THRESHOLDS -- not invented here. The rentabilidad dashboards
 * (`TabRentabilidad.jsx` and siblings, `getMarkupColor`) already paint
 * markup red below 0, orange below 3, yellow below 6 and green from 6 up.
 * This screen uses the same cut points with orange+yellow collapsed into one
 * amber "low" tone, so a sale reads the same colour here as its product does
 * there:
 *
 *   markup < 0       -> 'negative' (red)
 *   0 <= markup < 6  -> 'low'      (amber)
 *   markup >= 6      -> 'good'     (green)
 *   unknown          -> null       (no colour: unknown is never a zero)
 */

const MARKUP_LOW_THRESHOLD = 6;

const toNumber = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

export function markupTone(value) {
  const n = toNumber(value);
  if (n === null) return null;
  if (n < 0) return 'negative';
  if (n < MARKUP_LOW_THRESHOLD) return 'low';
  return 'good';
}

const PCT_FORMAT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 });

export function formatMarkup(value) {
  const n = toNumber(value);
  if (n === null) return '—';
  const text = `${PCT_FORMAT.format(Math.abs(n))}%`;
  if (n > 0) return `+${text}`;
  if (n < 0) return `-${text}`;
  return text;
}

export function moneyTone(value) {
  const n = toNumber(value);
  if (n === null) return null;
  if (n < 0) return 'negative';
  if (n > 0) return 'positive';
  return 'zero';
}

const MONEY_FORMAT = new Intl.NumberFormat('es-AR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** `-$ 74.676,08` / `$ 597.408,67` / `—` -- the minus goes BEFORE the sign. */
export function formatSignedMoney(value) {
  const n = toNumber(value);
  if (n === null) return '—';
  const text = `$ ${MONEY_FORMAT.format(Math.abs(n))}`;
  return n < 0 ? `-${text}` : text;
}

/**
 * A money cell of the listing: pesos read `$ 1.234,00` / `-$ 1.234,00`; a
 * foreign currency is spelled out (`82,50 USD`) instead of being passed off
 * as pesos. No currency means the listing's own (ARS).
 */
export function formatListMoney(value, currencyId) {
  const n = toNumber(value);
  if (n === null) return '—';
  if (!currencyId || currencyId === 'ARS') return formatSignedMoney(n);
  return `${n < 0 ? '-' : ''}${MONEY_FORMAT.format(Math.abs(n))} ${currencyId}`;
}

/**
 * A breakdown line's `monto` is a CHARGE: positive means it came off the
 * sale on its way to Neto. Rendered the way detalle.jpg does -- a "(−)"
 * line in red with "-$". A negative charge (ML refunded more than it billed)
 * genuinely ADDS to Neto and is shown as such, never as a double negative.
 */
export function formatDeduction(monto) {
  const n = toNumber(monto);
  if (n === null) return { sign: '(−)', text: '—', tone: null };
  if (n < 0) return { sign: '(+)', text: formatSignedMoney(-n), tone: 'positive' };
  return { sign: '(−)', text: formatSignedMoney(-n), tone: 'negative' };
}

// Mercado Libre's own shipment vocabulary, in Spanish. Substatus first: it
// is the finer reading ("En reparto" beats "En camino").
const SHIPPING_STATUS_LABELS = {
  pending: 'Pendiente',
  handling: 'En preparación',
  ready_to_ship: 'Listo para enviar',
  shipped: 'En camino',
  delivered: 'Entregado',
  not_delivered: 'No entregado',
  cancelled: 'Cancelado',
};

const SHIPPING_SUBSTATUS_LABELS = {
  ready_to_print: 'Etiqueta por imprimir',
  printed: 'Etiqueta impresa',
  in_packing_list: 'En lista de despacho',
  in_hub: 'En centro de distribución',
  picked_up: 'Retirado por el correo',
  out_for_delivery: 'En reparto',
  soon_deliver: 'Llega pronto',
  waiting_for_withdrawal: 'Esperando retiro',
  returned_to_warehouse: 'Devuelto al depósito',
  returning_to_sender: 'Volviendo al vendedor',
  delayed: 'Demorado',
};

/**
 * Human label for a shipment's state. A value we cannot translate is shown
 * verbatim -- a new ML status must not silently vanish -- but a translated
 * status always beats a raw substatus.
 */
export function shippingStatusLabel(shipment) {
  if (!shipment) return null;
  const { status, substatus } = shipment;
  if (substatus && SHIPPING_SUBSTATUS_LABELS[substatus]) return SHIPPING_SUBSTATUS_LABELS[substatus];
  if (status && SHIPPING_STATUS_LABELS[status]) return SHIPPING_STATUS_LABELS[status];
  return substatus || status || null;
}

// Status pill tones (`StatusPill`). The design paints the money axis green
// when it arrived, red when it did not, amber when it is in question.
export const OPERATION_STATUS_TONE = {
  paid: 'success',
  cancelled: 'danger',
  // ML's Buyer Protection paid it: the money arrived, it is not a loss.
  cancelled_ml_covered: 'info',
  in_dispute: 'warning',
  delivered: 'success',
  unknown: 'neutral',
  mixed: 'warning',
};

export const GOODS_STATUS_TONE = {
  unknown: 'neutral',
  in_warehouse: 'purple',
  in_transit: 'info',
  delivered: 'success',
  returned_undelivered: 'danger',
  mixed: 'warning',
};

export const MODO_LOGISTICO_TONE = {
  self_service: 'info',
  fulfillment: 'warning',
  cross_docking: 'neutral',
  retiro: 'neutral',
  desconocido: 'neutral',
  mixed: 'warning',
};

// Where the parcel is, in the detail panel's status dot colour.
const SHIPMENT_DOT_TONE = {
  delivered: 'success',
  shipped: 'info',
  ready_to_ship: 'warning',
  handling: 'warning',
  pending: 'neutral',
  not_delivered: 'danger',
  cancelled: 'danger',
};

export function shipmentDotTone(status) {
  return SHIPMENT_DOT_TONE[status] || 'neutral';
}
