import { eventLabel } from '../eventLabels';

/**
 * One event (`EventOut` of `routers/ml_publications_view.py`) as a sentence a
 * person reads: `title` says what happened, `detail` explains it, `change` is a
 * before → after pair (with how much a price moved). Nothing here guesses: a
 * value the event does not carry is left out, and an object is never shown.
 */

// The names `view/history_rows.py` gives the promotion types, so both tabs say the same.
const PROMOTION_TYPES = {
  DEAL: 'Campaña tradicional',
  MARKETPLACE_CAMPAIGN: 'Campaña de Mercado Libre',
  SELLER_CAMPAIGN: 'Campaña del vendedor',
  SELLER_COUPON_CAMPAIGN: 'Cupón del vendedor',
  SMART: 'Campaña co-fondeada',
  SMART_LIGHTNING: 'Oferta relámpago co-fondeada',
  LIGHTNING: 'Oferta relámpago',
  DOD: 'Oferta del día',
  PRICE_DISCOUNT: 'Descuento de precio',
  VOLUME: 'Descuento por volumen',
  PRE_NEGOTIATED: 'Descuento pre-acordado',
  UNHEALTHY_STOCK: 'Liquidación de stock',
};

const PRICE_KINDS = { standard: 'de lista', sale: 'de venta', promotion: 'de promoción' };

const toNumber = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

const pesos = (digits) => new Intl.NumberFormat('es-AR', { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** A figure as pesos: `$ 77.000`, cents only when there are any (`$ 84.467,35`); `null` when it is not a number. */
export function money(value) {
  const number = toNumber(value);
  if (number === null) return null;
  return `$ ${pesos(Number.isInteger(number) ? 0 : 2).format(number)}`;
}

/** How much a price moved, `+15,5 %` / `−15,6 %`; `null` without both sides. */
function delta(before, after) {
  const from = toNumber(before);
  const to = toNumber(after);
  if (from === null || to === null || from === 0 || from === to) return null;
  const percent = ((to - from) / from) * 100;
  const text = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(Math.abs(percent));
  return { text: `${percent > 0 ? '+' : '−'}${text} %`, direction: percent > 0 ? 'up' : 'down' };
}

const priceChange = (label, before, after) => ({ label, before: money(before), after: money(after), delta: delta(before, after) });

/** A plain value as text: a string or a number as it is; anything else (an object, a list) is not shown. */
const plain = (value) => (typeof value === 'string' || typeof value === 'number' ? String(value) : null);

/** Its own name (`promotion_name`), with its type in parentheses when known: `Tec Week (Campaña co-fondeada)`; `null` without a name. */
const namedPromotion = (event) => {
  if (!event.promotion_name) return null;
  const type = PROMOTION_TYPES[event.promotion_type];
  return type ? `${event.promotion_name} (${type})` : event.promotion_name;
};

/** "la promoción" and its name, else its type; "una promoción" when neither is known (never its code). */
const promotionName = (event) => {
  const name = namedPromotion(event) ?? PROMOTION_TYPES[event.promotion_type];
  return name ? `la promoción ${name}` : 'una promoción';
};

const sentence = (title, { detail = null, change = null } = {}) => ({ title, detail, change });

function promotionOffered(event) {
  const payload = event.payload ?? {};
  const suggested = money(payload.suggested_discounted_price);
  const min = money(payload.min_discounted_price);
  const max = money(payload.max_discounted_price);
  const parts = [suggested && `Precio sugerido ${suggested}`, min && max && `se puede elegir entre ${min} y ${max}`].filter(Boolean);
  return sentence(`ML ofreció ${namedPromotion(event) ?? promotionName(event)}`, { detail: parts.length ? parts.join(' · ') : null });
}

function promotionActivated(event) {
  const price = money(event.new_value);
  const subject = event.origin?.kind === 'nosotros' ? 'Activamos' : 'Se aplicó';
  const title = `${subject} ${promotionName(event)}${price ? ` a ${price}` : ''}`;
  const original = event.payload?.original_price;
  return sentence(title, { change: original != null && price ? priceChange('Precio de venta', original, event.new_value) : null });
}

function promotionFinished(event) {
  if (event.status_label === 'Finalizada') return sentence(`Terminó ${promotionName(event)}`);
  return sentence(`ML dejó de ofrecer ${promotionName(event)}`);
}

function priceChanged(event) {
  const kind = PRICE_KINDS[event.price_kind] ?? '';
  const change = priceChange(null, event.old_value, event.new_value);
  if (event.price_kind === 'promotion' && event.old_value == null) return sentence('Nuevo precio de promoción', { change });
  if (event.price_kind === 'promotion' && event.new_value == null) return sentence('Se quitó el precio de promoción', { change });
  return sentence(kind ? `Cambió el precio ${kind}` : 'Cambió el precio', { change });
}

function competitionWon(event) {
  const price = money(event.payload?.price_to_win);
  return sentence(price ? `Ganó el catálogo con ${price}` : 'Ganó el catálogo');
}

function competitionLost(event) {
  const title = event.new_value === 'not_listed' ? 'Dejó de competir en el catálogo' : 'Perdió el catálogo';
  return sentence(title, { detail: event.old_value === 'winning' ? 'Antes estaba ganando.' : null });
}

const quantities = (event, label) => ({ label, before: plain(event.old_value), after: plain(event.new_value), delta: null });

const BUILDERS = {
  promotion_offered: promotionOffered,
  promotion_activated: promotionActivated,
  promotion_finished: promotionFinished,
  promotion_price_changed: (event) =>
    sentence(`Cambió el precio de ${promotionName(event)}`, { change: priceChange(null, event.old_value, event.new_value) }),
  price_changed: priceChanged,
  status_activated: (event) => sentence(event.payload?.is_reactivation ? 'Publicación reactivada' : 'Publicación activada'),
  status_paused: () => sentence('Publicación pausada'),
  catalog_competition_won: competitionWon,
  catalog_competition_lost: competitionLost,
  stock_replenished: (event) => sentence('Volvió a tener stock', { change: quantities(event, 'Stock') }),
  stock_depleted: () => sentence('Se quedó sin stock'),
};

/** Any other type: its Spanish label, with its values when they are plain text or numbers. */
function generic(event) {
  const before = plain(event.old_value);
  const after = plain(event.new_value);
  return sentence(eventLabel(event.event_type), { change: before !== null || after !== null ? { label: null, before, after, delta: null } : null });
}

export function describeEvent(event) {
  return (BUILDERS[event.event_type] ?? generic)(event);
}

/** Who caused it (`origin.kind`), as the tag says it; ML's offers and metrics read as informative. */
export function originTag(origin, informational) {
  switch (origin?.kind) {
    case 'nosotros':
      return { text: origin.user_name ? `Hecho por nosotros · ${origin.user_name}` : 'Hecho por nosotros', tone: 'ours' };
    case 'automatico':
      return { text: 'Automático', tone: 'auto' };
    case 'ml':
      return { text: informational ? 'Informativo de ML' : 'Cambio de ML', tone: 'neutral' };
    case 'sin_registrar':
      return { text: 'Origen sin registrar', tone: 'neutral' };
    default:
      return null;
  }
}

const STATE_TONES = { 'Disponible para activar': 'warning', Aplicada: 'success', Pendiente: 'info' };

/** A promotion state's color: offered amber, applied green, pending blue, finished or gone neutral. */
export const stateTone = (label) => STATE_TONES[label] ?? 'neutral';

// ── Icons ────────────────────────────────────────────────────────────────────────────────────────────

const PLAY_TYPES = new Set(['status_activated', 'item_restored']);
const PAUSE_TYPES = new Set(['status_paused', 'status_closed', 'status_under_review', 'item_gone']);

/** The icon family of an event (`$` price, `%` promotion, play/pause, catalog star, stock) and its tone. */
export function eventIcon(event) {
  const type = event.event_type;
  if (type === 'price_changed' || type === 'promotion_price_changed') return { family: 'price', tone: 'warning' };
  if (type === 'promotion_activated') return { family: 'promotion', tone: 'info' };
  if (type.startsWith('promotion_')) return { family: 'promotion', tone: 'neutral' };
  if (PLAY_TYPES.has(type)) return { family: 'play', tone: 'success' };
  if (PAUSE_TYPES.has(type)) return { family: 'pause', tone: 'warning' };
  if (type === 'catalog_competition_won') return { family: 'star', tone: 'success' };
  if (type === 'catalog_competition_lost') return { family: 'star', tone: 'danger' };
  if (type.startsWith('stock_')) return { family: 'stock', tone: 'info' };
  return { family: 'other', tone: 'neutral' };
}

// ── Folding the offers ML made at once ───────────────────────────────────────────────────────────────

const PROMOTION_PLURALS = {
  DEAL: 'campañas tradicionales',
  MARKETPLACE_CAMPAIGN: 'campañas de Mercado Libre',
  SELLER_CAMPAIGN: 'campañas del vendedor',
  SELLER_COUPON_CAMPAIGN: 'cupones del vendedor',
  SMART: 'campañas co-fondeadas',
  SMART_LIGHTNING: 'ofertas relámpago co-fondeadas',
  LIGHTNING: 'ofertas relámpago',
  DOD: 'ofertas del día',
  PRICE_DISCOUNT: 'descuentos de precio',
  VOLUME: 'descuentos por volumen',
  PRE_NEGOTIATED: 'descuentos pre-acordados',
  UNHEALTHY_STOCK: 'liquidaciones de stock',
};

/** Only ML's informative offers fold: never one of ours, never one that applied anything. */
const foldable = (event) => event.event_type === 'promotion_offered' && event.informational === true && event.origin?.kind === 'ml';
const minute = (value) => Math.floor(Date.parse(value) / 60000);

/**
 * The lines of the list: consecutive foldable offers of the same minute share one line; every other event is a
 * line of its own. Each line is `{ events }`, in the order received.
 */
export function foldOffers(events) {
  const lines = [];
  for (const event of events) {
    const last = lines.at(-1);
    const head = last?.events[0];
    if (head && foldable(head) && foldable(event) && minute(head.observed_at) === minute(event.observed_at)) {
      last.events.push(event);
    } else {
      lines.push({ events: [event] });
    }
  }
  return lines;
}

const joinNames = (names) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} y ${names.at(-1)}`);

/**
 * A folded line: the offers counted per type ("3 campañas del vendedor", "Campaña co-fondeada y …"); the detail
 * names them ("A PVP TODO, Tec Week y 1 más", the unnamed counted last), or without any name the detail they share.
 */
export function describeOffers(events) {
  const counts = new Map();
  for (const event of events) counts.set(event.promotion_type, (counts.get(event.promotion_type) ?? 0) + 1);
  const names = [...counts].map(([type, count]) => {
    if (count > 1) return `${count} ${PROMOTION_PLURALS[type] ?? 'promociones'}`;
    return PROMOTION_TYPES[type] ?? 'una promoción';
  });
  const title = `ML ofreció ${joinNames(names)}`;
  const named = events.map((event) => event.promotion_name).filter(Boolean);
  if (named.length) {
    const unnamed = events.length - named.length;
    return sentence(title, { detail: joinNames(unnamed ? [...named, `${unnamed} más`] : named) });
  }
  const details = new Set(events.map((event) => promotionOffered(event).detail));
  return sentence(title, { detail: details.size === 1 ? [...details][0] : null });
}
