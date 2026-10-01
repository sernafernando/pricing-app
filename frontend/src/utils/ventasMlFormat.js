/**
 * Formatting/label helpers for the Ventas ML table, extracted from
 * `VentasML.jsx` (ventas-ml-columnas) so `ventasMlColumns.jsx` can use them
 * without an import cycle back into the page module. Behaviour is copied
 * verbatim — no formatting/label decision changed by this extraction.
 */

// Locale pinned, like every other page in the app (`Prearmado.jsx`,
// `DashboardMetricasML.jsx`). Left to the browser, a client in en-US
// renders MM/DD and AM/PM in the middle of a DD/MM table.
const DATE_FORMAT = new Intl.DateTimeFormat('es-AR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export function formatDate(value) {
  if (!value) return '—';
  return DATE_FORMAT.format(new Date(value));
}

// The listing is denominated in ARS, so repeating "ARS" on every row costs
// the width the amount itself needs. Only a foreign currency is spelled out.
export const LISTING_IMPLIED_CURRENCY = 'ARS';

export function formatAmount(value) {
  return new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

export function formatMoneyFull(value, currencyId) {
  if (value === null || value === undefined) return '—';
  const amount = formatAmount(value);
  return currencyId ? `${amount} ${currencyId}` : amount;
}

// Tooltip for a money cell: the unabridged value, or nothing at all. A
// `title` is still a way of reading the number, so it obeys the same rule
// as the visible cell -- while metrics are being recalculated the stale
// figure must not surface anywhere (SM R3/R9), and an absent value gets no
// tooltip rather than a tooltip reading "—".
export function moneyTitle(value, currencyId, metricsState) {
  if (metricsState && metricsState !== 'ok') return undefined;
  if (value === null || value === undefined) return undefined;
  return formatMoneyFull(value, currencyId);
}

export function formatMoney(value, currencyId) {
  if (value === null || value === undefined) return '—';
  const amount = formatAmount(value);
  if (!currencyId || currencyId === LISTING_IMPLIED_CURRENCY) return amount;
  return `${amount} ${currencyId}`;
}

export function netoTooltip(netoDepositado, retencionesRecuperables) {
  if (!(retencionesRecuperables > 0)) return undefined;
  return `MP $ ${new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(netoDepositado))} · SIRTAC $ ${new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(retencionesRecuperables))}`;
}

export const OPERATION_STATUS_LABELS = {
  paid: 'Pagada',
  cancelled: 'Cancelada',
  // A cancellation Mercado Libre covered through its Buyer Protection
  // Programme — the money still arrived, so this must not read as a plain
  // cancellation.
  cancelled_ml_covered: 'Cubierta por ML',
  in_dispute: 'En disputa',
  delivered: 'Entregada',
  unknown: 'A revisar',
  // Not a status the backend derives per order — the pack's orders
  // disagree. Never render a winner.
  mixed: 'Mixta',
};

export const OPERATION_STATUS_BADGE_CLASS = {
  paid: 'badge-primary',
  cancelled: 'badge-danger',
  cancelled_ml_covered: 'badge-success',
  in_dispute: 'badge-warning',
  delivered: 'badge-success',
  unknown: 'badge-neutral',
  mixed: 'badge-warning',
};

// `mixed` is deliberately NOT a filter chip: it is a property of a row,
// not a value any order carries, so there is nothing to filter on.
export const OPERATION_STATUS_OPTIONS = Object.keys(OPERATION_STATUS_LABELS).filter((v) => v !== 'mixed');

export const GOODS_STATUS_LABELS = {
  unknown: 'A revisar',
  in_warehouse: 'En depósito',
  in_transit: 'En tránsito',
  delivered: 'Entregado',
  returned_undelivered: 'Devuelto sin entregar',
  mixed: 'Mixta',
};

export const GOODS_STATUS_BADGE_CLASS = {
  unknown: 'badge-neutral',
  in_warehouse: 'badge-primary',
  in_transit: 'badge-warning',
  delivered: 'badge-success',
  returned_undelivered: 'badge-danger',
  mixed: 'badge-warning',
};

export const GOODS_STATUS_OPTIONS = Object.keys(GOODS_STATUS_LABELS).filter((v) => v !== 'mixed');

// ml-ventas-modo-logistico PR6: `modo_logistico` badge. Known values come
// straight from `MlShipmentOps.logistic_type` (`resolve_modo_logistico`,
// backend): `self_service` is Flex, `fulfillment` is Full, `cross_docking`
// is Colecta. `retiro` is the tag-only fallback when there is no shipment
// at all. An UNRECOGNISED value is rendered VERBATIM — never folded into
// "desconocido" — because the backend passes a future ML logistic type
// through on purpose so it cannot silently vanish here.
export const MODO_LOGISTICO_LABELS = {
  self_service: 'Flex',
  fulfillment: 'Full',
  cross_docking: 'Colecta',
  retiro: 'Retiro',
  desconocido: 'Desconocido',
  // The group's modo_logistico when its orders disagree — same "mixed"
  // discipline as the two status axes above.
  mixed: 'Mixto',
};

export const MODO_LOGISTICO_BADGE_CLASS = {
  self_service: 'badge-primary',
  fulfillment: 'badge-success',
  cross_docking: 'badge-warning',
  retiro: 'badge-neutral',
  desconocido: 'badge-neutral',
  mixed: 'badge-warning',
};

// Worst-first, same discipline as the existing status "mixed" precedent:
// a pack with any order in `error` reads as `error`, not an average.
export function groupAlertLevel(orders) {
  if (orders.some((o) => o.alert_level === 'error')) return 'error';
  if (orders.some((o) => o.alert_level === 'warning')) return 'warning';
  return 'ok';
}

// Same precedence as `RecalculatingBadge` expects: `recalculating` beats
// `failed` beats `pending` beats `ok`, so the pack row never claims a
// stale/finished state while one of its orders is still catching up.
export function groupMetricsState(orders) {
  if (orders.some((o) => o.metrics_state === 'recalculating')) return 'recalculating';
  if (orders.some((o) => o.metrics_state === 'failed')) return 'failed';
  if (orders.some((o) => o.metrics_state === 'pending')) return 'pending';
  return 'ok';
}

// A pack's icon is only shown when every order agrees on `item_category` --
// showing one item's category for a multi-item parcel would misrepresent
// the other items, so this renders nothing (falls back to no icon) instead
// of picking an arbitrary member.
export function groupCategory(orders) {
  const categories = new Set(orders.map((o) => o.item_category).filter(Boolean));
  return categories.size === 1 ? [...categories][0] : null;
}

// ventas-ml-producto-listado-pr10b (PR14.T5/T6 blocker): a pack's row is
// one PARCEL but can carry several orders, each with its own item(s) — the
// collapsed row must represent EVERY item across the whole pack, never
// just the first order's.
export function groupItems(orders) {
  return orders.flatMap((o) => o.items || []);
}

// PR14 review fix P3: mirrors `_alert_level`'s own precedence
// (`ml_ventas_ops.py`) using only the fields the listing endpoint actually
// exposes per order.
export function orderAlertReason(order) {
  if (!order) return undefined;
  if (order.metrics_state === 'failed') return 'El recálculo de esta venta falló.';
  if (order.metrics_state === 'pending') return 'Todavía no se calculó esta venta.';
  if (order.neto == null) return 'El neto de esta venta es desconocido.';
  if (order.metrics_state === 'recalculating') return 'Esta venta se está recalculando.';
  if (order.operation_status === 'unknown') return 'El estado de la operación todavía no se clasificó.';
  if (order.goods_status === 'unknown') return 'El estado de la mercadería todavía no se clasificó.';
  return 'Esta venta requiere revisión.';
}

// The group row's own alert_level is the worst among its orders
// (`groupAlertLevel`). The reason shown must come from an order that
// actually carries that level -- never a guess picked from an unrelated
// member.
export function groupAlertReason(orders, level) {
  const culprit = orders.find((o) => o.alert_level === level);
  return orderAlertReason(culprit);
}

// ML coupon (`coupon_amount`, summed per order by the backend over the
// order's relevant payments). A pack's coupon is the sum of its orders'.
// `null` = nothing to show: zero, absent and non-numeric all read the same,
// the sub-line only exists when a coupon was actually applied.
export function couponAmountOf(orders) {
  let sum = 0;
  for (const order of orders || []) {
    const value = Number(order?.coupon_amount);
    if (Number.isFinite(value)) sum += value;
  }
  return sum > 0 ? sum : null;
}

const DAY_FORMAT = new Intl.DateTimeFormat('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });

/** Day only (no time), `—` for an absent or unparseable value. */
export function formatDay(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : DAY_FORMAT.format(date);
}

// Seller-side sale page on Mercado Libre. A pack is one purchase in ML's
// sales screen, so it is addressed by `pack_id` when there is one. Built from
// data we already hold; `null` (link hidden) without an id.
export function mlSaleUrl({ orderId, packId }) {
  const id = packId ?? orderId;
  if (id === null || id === undefined) return null;
  return `https://www.mercadolibre.com.ar/ventas/${id}/detalle`;
}

const PAYMENT_METHOD_LABELS = {
  account_money: 'Dinero en cuenta',
  visa: 'Visa',
  debvisa: 'Visa débito',
  master: 'Mastercard',
  debmaster: 'Mastercard débito',
  amex: 'American Express',
  naranja: 'Naranja',
  cabal: 'Cabal',
  consumer_credit: 'Cuotas sin tarjeta (Mercado Crédito)',
  debit_card: 'Tarjeta de débito',
  credit_card: 'Tarjeta de crédito',
};

/** Human name for ML's `payment_method_id`; an unknown id is shown raw. */
export function paymentMethodLabel(id) {
  if (!id) return null;
  return PAYMENT_METHOD_LABELS[id] || id;
}

/**
 * "hace 3 min" for a past timestamp; `null` when there is none (the caller
 * then shows nothing rather than a made-up freshness). `now` is injectable so
 * the text is testable; it is evaluated at render time, no timers involved.
 */
export function timeAgo(value, now = new Date()) {
  if (!value) return null;
  const then = new Date(value);
  if (Number.isNaN(then.getTime())) return null;
  const seconds = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 1000));
  if (seconds < 60) return 'hace instantes';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.floor(hours / 24)} d`;
}
