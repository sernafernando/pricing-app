/** Pick SMART / DEAL / Premium+month candidates for MODO PONER PRECIOS Enter. */

import { resolvePromoName } from '../../promociones/resolvePromoName';
import { promoDisplayPrice } from '../../promociones/promoDisplayPrice';

const MONTHS_ES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
];

/** Keep in sync with backend `COFUNDED_PROMOTION_TYPES` (ml_promotions_pricing). */
export const COFUNDED_PROMOTION_TYPES = new Set(['SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING']);

/** Pesos: sale vs started offer can differ by cents. Keep in sync with backend tolerance. */
const BASELINE_PRICE_TOLERANCE_ARS = 1;

export function pricesClose(left, right, tolerance = BASELINE_PRICE_TOLERANCE_ARS) {
  if (left == null || right == null) return false;
  const a = Number(left);
  const b = Number(right);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  return Math.abs(a - b) <= tolerance;
}

/**
 * Status-quo markup for the chooser: co-funded started offer matching
 * `baselinePrice` (same chain as the promo card / backend
 * `markup_baseline_vigente`: max among matches), else null so the caller
 * falls back to `getMarkupParaPrecio` (plain sale, no co-funding).
 */
export function baselineMarkupFromPromos(promotions, baselinePrice) {
  if (baselinePrice == null || !Number.isFinite(Number(baselinePrice))) return null;
  const started = (promotions || []).filter(
    (promo) =>
      promo?.status === 'started' &&
      COFUNDED_PROMOTION_TYPES.has(promo.promotion_type) &&
      typeof promo.nuestro_markup === 'number' &&
      Number.isFinite(promo.nuestro_markup) &&
      pricesClose(promoDisplayPrice(promo), baselinePrice),
  );
  if (!started.length) return null;
  return Math.max(...started.map((promo) => promo.nuestro_markup));
}

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

/**
 * Keep in sync with backend `es_mejor_oferta` (ml_promotions_hay_mejores.py):
 * markup↑ same price; markup= lower; markup↑ lower. Higher consumer price never better.
 * Shared cases: same+higher markup ✓; same+same markup ✗; higher price+higher markup ✗;
 * lower price+same markup ✓; lower price+higher markup ✓; lower price+lower markup ✗.
 */
export function esMejorOferta(candidatePrice, candidateMarkup, baselinePrice, baselineMarkup) {
  if (candidatePrice == null || candidateMarkup == null) return false;
  if (baselinePrice == null || baselineMarkup == null) return false;
  if (!(Number.isFinite(candidatePrice) && Number.isFinite(candidateMarkup))) return false;
  if (!(Number.isFinite(baselinePrice) && Number.isFinite(baselineMarkup))) return false;
  if (candidatePrice > baselinePrice) return false;
  if (candidatePrice === baselinePrice) return candidateMarkup > baselineMarkup;
  return candidateMarkup >= baselineMarkup;
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

function pickSlots(candidates, monthName) {
  return {
    smart: bestByMarkup(candidates.filter((p) => p.promotion_type === 'SMART')),
    deal: bestByMarkup(candidates.filter((p) => p.promotion_type === 'DEAL')),
    premium: bestByMarkup(
      candidates.filter((p) => p.promotion_type === 'SELLER_CAMPAIGN' && isPremiumCurrentMonth(p, monthName)),
    ),
  };
}

export function pickPonerPreciosPromos(promotions, { monthName = currentMonthNameEs() } = {}) {
  const candidates = (promotions || []).filter((promo) => promo?.status === 'candidate');
  return pickSlots(candidates, monthName);
}

/** Best SMART/DEAL/Premium that beat the MeLi status quo (flagged-pub chooser). */
export function pickMejoresCandidatas(
  promotions,
  { baselinePrice, baselineMarkup, monthName = currentMonthNameEs() } = {},
) {
  const candidates = (promotions || []).filter((promo) => promo?.status === 'candidate');
  const better = candidates.filter((promo) =>
    esMejorOferta(promoDisplayPrice(promo), markupOf(promo), baselinePrice, baselineMarkup),
  );
  return pickSlots(better, monthName);
}

export function hasPickedSlot(picked) {
  return Boolean(picked?.smart || picked?.deal || picked?.premium);
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
