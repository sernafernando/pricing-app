/** Pick SMART / DEAL / Premium+month candidates for MODO PONER PRECIOS Enter. */

import { resolvePromoName } from '../../promociones/resolvePromoName';
import { promoDisplayPrice } from '../../promociones/promoDisplayPrice';

const MONTHS_ES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
];

export function currentMonthNameEs(now = new Date()) {
  return MONTHS_ES[now.getMonth()];
}

export function isPremiumCurrentMonth(promo, monthName) {
  const name = (resolvePromoName(promo) || '').toLowerCase();
  return name.includes('premium') && name.includes(String(monthName).toLowerCase());
}

function markupOf(promo) {
  const value = promo?.nuestro_markup;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Best candidate by `nuestro_markup`. Skips null/non-finite markups (no arbitrary first pick). */
export function bestByMarkup(promos) {
  let best = null;
  let bestMarkup = -Infinity;
  for (const promo of promos) {
    const markup = markupOf(promo);
    if (markup == null) continue;
    if (markup > bestMarkup) {
      best = promo;
      bestMarkup = markup;
    }
  }
  return best;
}

export function pickPonerPreciosPromos(promotions, { monthName = currentMonthNameEs() } = {}) {
  const candidates = (promotions || []).filter((promo) => promo?.status === 'candidate');
  return {
    smart: bestByMarkup(candidates.filter((p) => p.promotion_type === 'SMART')),
    deal: bestByMarkup(candidates.filter((p) => p.promotion_type === 'DEAL')),
    premium: bestByMarkup(
      candidates.filter((p) => p.promotion_type === 'SELLER_CAMPAIGN' && isPremiumCurrentMonth(p, monthName)),
    ),
  };
}

export function enrollBodyForPromo(promo) {
  const type = promo.promotion_type;
  const body = { promotion_id: promo.promotion_id, promotion_type: type };
  if (type === 'SMART' || type === 'PRE_NEGOTIATED' || type === 'PRICE_MATCHING') {
    body.precio_visto = Number(promoDisplayPrice(promo));
    if (promo.nuestro_markup != null) body.markup_visto = promo.nuestro_markup;
    return body;
  }
  const suggested = Number(promo.suggested_discounted_price ?? promo.price);
  const min = promo.min_discounted_price;
  const max = promo.max_discounted_price;
  let dealPrice = suggested;
  if (Number.isFinite(min) && Number.isFinite(max) && Number.isFinite(suggested)) {
    dealPrice = Math.min(max, Math.max(min, suggested));
  }
  if (Number.isFinite(dealPrice) && dealPrice > 0) body.deal_price = dealPrice;
  return body;
}

export function listRowForPricelist(pricelistId, lists) {
  for (const list of lists) {
    const row = list.rows.find((entry) => entry.pricelist === pricelistId);
    if (row) return row;
  }
  return null;
}
