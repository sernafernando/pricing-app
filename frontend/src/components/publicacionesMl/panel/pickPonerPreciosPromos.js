/** Pick enrollable candidates for hay_mejores chooser / MODO Enter. */

import { resolvePromoName } from '../../promociones/resolvePromoName';
import { promoDisplayPrice } from '../../promociones/promoDisplayPrice';
import {
  APPLICABLE_PROMOTION_TYPES,
  COFUNDED_PROMOTION_TYPES,
  SMART_LIKE_PROMOTION_TYPES,
} from '../../promociones/applicablePromoTypes';

export { COFUNDED_PROMOTION_TYPES };

const MONTHS_ES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
];

/**
 * Chooser / Enter slots keyed by MeLi `promotion_type` (labels = same string).
 * `SELLER_CAMPAIGN` is Premium+current-month only.
 * `SMART_LIGHTNING` stays listed for when writables expand; gated by
 * `APPLICABLE_PROMOTION_TYPES` (not applicable today).
 */
export const CHOOSER_SLOT_TYPES = [
  'SMART',
  'DEAL',
  'PRE_NEGOTIATED',
  'PRICE_MATCHING',
  'LIGHTNING',
  'SMART_LIGHTNING',
  'SELLER_CAMPAIGN',
];

/** MeLi type name as button label (Premium is still SELLER_CAMPAIGN). */
export const CHOOSER_SLOT_LABELS = Object.fromEntries(
  CHOOSER_SLOT_TYPES.map((type) => [type, type]),
);

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

/**
 * An ML promotion date as epoch ms, or null when missing or unparseable. Naive values are UTC (as the backend reads
 * them: `new Date()` would read them as local time); a date-only value starts its day, or with `endOfDay` the next one.
 * Keep in sync with backend `parse_promo_instant` (ml_promotions_aplicable.py).
 */
export function parsePromoInstant(value, { endOfDay = false } = {}) {
  if (!value || typeof value !== 'string') return null;
  // A space between date and time is valid ISO for the backend's `fromisoformat` too.
  const text = value.trim().replace(/^(\d{4}-\d{2}-\d{2}) (?=\d{2}:)/, '$1T');
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(text);
  if (!dateOnly && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text)) return null;
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(text);
  const ms = Date.parse(dateOnly ? `${text}T00:00:00Z` : hasZone ? text : `${text}Z`);
  if (!Number.isFinite(ms)) return null;
  return dateOnly && endOfDay ? ms + 24 * 60 * 60 * 1000 : ms;
}

/**
 * Whether a candidate can be applied at `now` (owner: "no me sirve una promo mejor que voy a poder aplicar recién en
 * 10 días"): writable type, started (or no start), not finished (or no finish), SELLER_CAMPAIGN only as the Premium of
 * the month. Keep in sync with backend `candidata_aplicable_ahora` (ml_promotions_aplicable.py); both run the shared
 * cases in `backend/tests/fixtures/candidata_aplicable_cases.json`.
 */
export function isApplicableNow(promo, { now = new Date(), monthName = currentMonthNameEs(now) } = {}) {
  const type = promo?.promotion_type;
  if (!APPLICABLE_PROMOTION_TYPES.has(type)) return false;
  const at = now.getTime();
  const start = parsePromoInstant(promo.start_date);
  if (start != null && start > at) return false;
  const finish = parsePromoInstant(promo.finish_date, { endOfDay: true });
  if (finish != null && finish <= at) return false;
  if (type === 'SELLER_CAMPAIGN' && !isPremiumCurrentMonth(promo, monthName)) return false;
  return true;
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

function lightningHasStockRange(promo) {
  const stock = promo?.payload?.stock;
  return Number.isInteger(stock?.min) && Number.isInteger(stock?.max);
}

function matchesChooserSlot(promo, type, monthName) {
  if (promo?.promotion_type !== type) return false;
  if (type === 'SELLER_CAMPAIGN') return isPremiumCurrentMonth(promo, monthName);
  // Same gate as PromoApplyControl: without ML stock range, enroll cannot succeed.
  if (type === 'LIGHTNING') return lightningHasStockRange(promo);
  return true;
}

/**
 * One best-by-markup promo per MeLi type that is both in the slot table and
 * currently applicable (writable). Keys are MeLi type strings.
 */
export function pickSlots(candidates, monthName, applicableTypes = APPLICABLE_PROMOTION_TYPES) {
  const picked = {};
  for (const type of CHOOSER_SLOT_TYPES) {
    if (!applicableTypes.has(type)) {
      picked[type] = null;
      continue;
    }
    picked[type] = bestByMarkup(
      candidates.filter((promo) => matchesChooserSlot(promo, type, monthName)),
    );
  }
  return picked;
}

export function pickPonerPreciosPromos(promotions, { monthName = currentMonthNameEs() } = {}) {
  const candidates = (promotions || []).filter((promo) => promo?.status === 'candidate');
  return pickSlots(candidates, monthName);
}

/**
 * Best enrollable slot per type among the candidates applicable now that beat the MeLi status quo. The status quo's plain markup is
 * `baselineMarkup` and its markup with sell in / sell out `baselineSellInOut`; each candidate is compared on the
 * basis `comparableMarkups` picks.
 */
export function pickMejoresCandidatas(
  promotions,
  { baselinePrice, baselineMarkup, baselineSellInOut = null, now = new Date(), monthName = currentMonthNameEs(now) } = {},
) {
  const baseline = { nuestro_markup: baselineMarkup, markup_sell_in_out: baselineSellInOut };
  // Only candidates applicable now, as the backend flag counts them (`candidata_aplicable_ahora`).
  const candidates = (promotions || []).filter(
    (promo) => promo?.status === 'candidate' && isApplicableNow(promo, { now, monthName }),
  );
  const better = candidates.filter((promo) => {
    const [candidateMarkup, statusQuoMarkup] = comparableMarkups(promo, baseline);
    return esMejorOferta(promoDisplayPrice(promo), candidateMarkup, baselinePrice, statusQuoMarkup);
  });
  return pickSlots(better, monthName);
}

export function hasPickedSlot(picked) {
  if (!picked) return false;
  return CHOOSER_SLOT_TYPES.some((type) => Boolean(picked[type]));
}

/** Ordered [type, promo] pairs for UI buttons. */
export function slotEntries(picked) {
  if (!picked) return [];
  return CHOOSER_SLOT_TYPES.filter((type) => picked[type]).map((type) => [type, picked[type]]);
}

function positiveBound(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

export function enrollBodyForPromo(promo) {
  const type = promo.promotion_type;
  const body = { promotion_id: promo.promotion_id, promotion_type: type };
  if (SMART_LIKE_PROMOTION_TYPES.has(type)) {
    body.precio_visto = Number(promoDisplayPrice(promo));
    if (promo.nuestro_markup != null) body.markup_visto = promo.nuestro_markup;
    return body;
  }
  if (type === 'LIGHTNING') {
    const dealPrice = Number(promoDisplayPrice(promo));
    if (Number.isFinite(dealPrice) && dealPrice > 0) body.deal_price = dealPrice;
    // Chooser default: reserve the minimum ML allows; panel UI can refine stock.
    const stockMin = promo.payload?.stock?.min;
    if (Number.isInteger(stockMin)) body.stock = stockMin;
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
