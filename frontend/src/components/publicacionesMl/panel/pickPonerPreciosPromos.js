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
  return baselinePromo(promotions, baselinePrice)?.nuestro_markup ?? null;
}

/**
 * The `markup_sell_in_out` of the same status-quo offer `baselineMarkupFromPromos` takes its
 * markup from (promos-markup-sell-in-out), null when there is none or it has no sell in / sell out.
 */
export function baselineSellInOutFromPromos(promotions, baselinePrice) {
  return baselinePromo(promotions, baselinePrice)?.markup_sell_in_out ?? null;
}

function baselinePromo(promotions, baselinePrice) {
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
  // The best markup among the matches (backend `markup_baseline_vigente`); the first on a tie.
  return started.reduce((best, promo) => (promo.nuestro_markup > best.nuestro_markup ? promo : best));
}

export function currentMonthNameEs(now = new Date()) {
  return MONTHS_ES[now.getMonth()];
}

export function isPremiumCurrentMonth(promo, monthName) {
  const name = (resolvePromoName(promo) || '').toLowerCase();
  return name.includes('premium') && name.includes(String(monthName).toLowerCase());
}

const finiteOrNull = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/**
 * (candidate, status quo) markups on the SAME basis (S5, owner: "va a tener que usar el sell in sell out"): with
 * sell in / sell out when both have it, else both plain, so a figure with sell in / sell out is never compared
 * against a plain one. Each side is `{ nuestro_markup, markup_sell_in_out }`.
 * Keep in sync with backend `markups_comparables` (ml_promotions_hay_mejores.py).
 */
export function comparableMarkups(candidate, baseline) {
  const candidateSellInOut = finiteOrNull(candidate?.markup_sell_in_out);
  const baselineSellInOut = finiteOrNull(baseline?.markup_sell_in_out);
  const candidatePlain = finiteOrNull(candidate?.nuestro_markup);
  const baselinePlain = finiteOrNull(baseline?.nuestro_markup);
  if (candidatePlain != null && baselinePlain != null && candidateSellInOut != null && baselineSellInOut != null) {
    return [candidateSellInOut, baselineSellInOut];
  }
  return [candidatePlain, baselinePlain];
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

/**
 * Best candidate by markup, on one basis for the whole set (the same rule as `comparableMarkups`): with sell in /
 * sell out when every candidate has it, else all plain. Skips promos without `nuestro_markup` (no arbitrary pick).
 */
export function bestByMarkup(promos) {
  const ranked = promos.filter((promo) => finiteOrNull(promo?.nuestro_markup) != null);
  const withSellInOut = ranked.every((promo) => finiteOrNull(promo.markup_sell_in_out) != null);
  const key = withSellInOut ? 'markup_sell_in_out' : 'nuestro_markup';
  let best = null;
  for (const promo of ranked) {
    if (best == null || promo[key] > best[key]) best = promo;
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

/**
 * Best SMART/DEAL/Premium that beat the MeLi status quo (flagged-pub chooser). The status quo's plain markup is
 * `baselineMarkup` and its markup with sell in / sell out `baselineSellInOut`; each candidate is compared on the
 * basis `comparableMarkups` picks.
 */
export function pickMejoresCandidatas(
  promotions,
  { baselinePrice, baselineMarkup, baselineSellInOut = null, monthName = currentMonthNameEs() } = {},
) {
  const baseline = { nuestro_markup: baselineMarkup, markup_sell_in_out: baselineSellInOut };
  const candidates = (promotions || []).filter((promo) => promo?.status === 'candidate');
  const better = candidates.filter((promo) => {
    const [candidateMarkup, statusQuoMarkup] = comparableMarkups(promo, baseline);
    return esMejorOferta(promoDisplayPrice(promo), candidateMarkup, baselinePrice, statusQuoMarkup);
  });
  return pickSlots(better, monthName);
}

export function hasPickedSlot(picked) {
  return Boolean(picked?.smart || picked?.deal || picked?.premium);
}

function positiveBound(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

export function enrollBodyForPromo(promo) {
  const type = promo.promotion_type;
  const body = { promotion_id: promo.promotion_id, promotion_type: type };
  if (type === 'SMART' || type === 'PRE_NEGOTIATED' || type === 'PRICE_MATCHING') {
    body.precio_visto = Number(promoDisplayPrice(promo));
    if (promo.nuestro_markup != null) body.markup_visto = promo.nuestro_markup;
    return body;
  }
  // A DEAL is applied at the price its row shows (promoDisplayPrice: its max, the smallest discount
  // ML accepts); other range types keep ML's suggestion. Clamped to [min, max] below.
  // A missing price stays NaN (never 0), so it is not clamped up to the min and nothing is sent.
  const startPrice = Number(
    (type === 'DEAL' ? promoDisplayPrice(promo) : (promo.suggested_discounted_price ?? promo.price)) ?? NaN,
  );
  // Each bound ML sends clamps on its own, the same way promoDisplayPrice does.
  const min = positiveBound(promo.min_discounted_price);
  const max = positiveBound(promo.max_discounted_price);
  let dealPrice = startPrice;
  if (Number.isFinite(dealPrice)) {
    if (max != null) dealPrice = Math.min(dealPrice, max);
    if (min != null) dealPrice = Math.max(dealPrice, min);
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
