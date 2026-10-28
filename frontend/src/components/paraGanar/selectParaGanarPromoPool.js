import { ML_PRICED_TYPES, promoDisplayPrice } from '../promociones/promoDisplayPrice';

/** Seller-priced promos that take an explicit deal_price (not ML-priced SMART). */
export const SELLER_PRICED_TYPES = new Set(['DEAL', 'SELLER_CAMPAIGN']);

/** Slot labels for the Advisor pool (D19/D20): at most 3 suggestions. */
export const POOL_SLOT_LABELS = ['Mejor', 'Intermedia', 'Tercera'];

function isCandidate(promo) {
  return promo?.status === 'candidate';
}

/** Premium campaigns are named e.g. "PREMIUM JULIO" (month changes; "premium" stays). */
export function isPremiumPromo(promo) {
  const blob = `${promo?.name || ''} ${promo?.payload?.name || ''}`.toLowerCase();
  return blob.includes('premium');
}

function inDealRange(promo, precioSugerido) {
  if (precioSugerido == null || !Number.isFinite(Number(precioSugerido))) {
    return true;
  }
  const target = Number(precioSugerido);
  const min = promo.min_discounted_price;
  const max = promo.max_discounted_price;
  if (min != null && Number.isFinite(Number(min)) && target < Number(min)) return false;
  if (max != null && Number.isFinite(Number(max)) && target > Number(max)) return false;
  return true;
}

function fitsMarkupBand(promo, markupMin, markupMax) {
  const raw = promo.nuestro_markup;
  if (raw == null || !Number.isFinite(Number(raw))) return true;
  const value = Number(raw);
  if (markupMin != null && Number.isFinite(Number(markupMin)) && value < Number(markupMin)) {
    return false;
  }
  if (markupMax != null && Number.isFinite(Number(markupMax)) && value > Number(markupMax)) {
    return false;
  }
  return true;
}

function fitsCriteria(promo, { precioSugerido, markupMin, markupMax }) {
  if (!isCandidate(promo)) return false;
  const type = promo.promotion_type;
  if (!ML_PRICED_TYPES.has(type) && !SELLER_PRICED_TYPES.has(type)) return false;
  if (!fitsMarkupBand(promo, markupMin, markupMax)) return false;
  if (SELLER_PRICED_TYPES.has(type) && !inDealRange(promo, precioSugerido)) return false;
  return true;
}

/** Lower score = closer to suggested price (or range midpoint). */
function closenessScore(promo, precioSugerido) {
  if (precioSugerido == null || !Number.isFinite(Number(precioSugerido))) return 0;
  const target = Number(precioSugerido);
  if (ML_PRICED_TYPES.has(promo.promotion_type)) {
    const offer = promoDisplayPrice(promo);
    if (offer == null) return Number.POSITIVE_INFINITY;
    return Math.abs(offer - target);
  }
  const min =
    promo.min_discounted_price != null && Number.isFinite(Number(promo.min_discounted_price))
      ? Number(promo.min_discounted_price)
      : target;
  const max =
    promo.max_discounted_price != null && Number.isFinite(Number(promo.max_discounted_price))
      ? Number(promo.max_discounted_price)
      : target;
  return Math.abs((min + max) / 2 - target);
}

function sortByCloseness(list, precioSugerido) {
  return [...list].sort((a, b) => {
    const delta = closenessScore(a, precioSugerido) - closenessScore(b, precioSugerido);
    if (delta !== 0) return delta;
    return String(a.name || a.promotion_id || '').localeCompare(
      String(b.name || b.promotion_id || ''),
    );
  });
}

/**
 * PARA GANAR pool (D20): up to 3 slots by type — one SMART, one other DEAL/campaña,
 * one Premium (name contains "premium"). Premium keeps the last slot when it fits;
 * brand-specific campaigns (A PVP …) may appear as the single "other" pick but no
 * longer crowd Premium out.
 *
 * @param {Array<object>} promotions
 * @param {{ precioSugerido?: number|null, markupMin?: number|null, markupMax?: number|null }} [opts]
 * @returns {Array<object>} rows with pool_slot / pool_rank
 */
export function selectParaGanarPromoPool(promotions, opts = {}) {
  const { precioSugerido = null, markupMin = null, markupMax = null } = opts;
  const eligible = (Array.isArray(promotions) ? promotions : []).filter((p) =>
    fitsCriteria(p, { precioSugerido, markupMin, markupMax }),
  );

  const smart = sortByCloseness(
    eligible.filter((p) => ML_PRICED_TYPES.has(p.promotion_type)),
    precioSugerido,
  );
  const premium = sortByCloseness(
    eligible.filter((p) => isPremiumPromo(p) && !ML_PRICED_TYPES.has(p.promotion_type)),
    precioSugerido,
  );
  const other = sortByCloseness(
    eligible.filter(
      (p) =>
        SELLER_PRICED_TYPES.has(p.promotion_type) &&
        !isPremiumPromo(p) &&
        !ML_PRICED_TYPES.has(p.promotion_type),
    ),
    precioSugerido,
  );

  const slots = [];
  if (smart[0]) slots.push(smart[0]);
  if (other[0]) slots.push(other[0]);
  if (premium[0]) slots.push(premium[0]);

  return slots.map((promo, index) => ({
    ...promo,
    pool_slot: POOL_SLOT_LABELS[index],
    pool_rank: index + 1,
  }));
}
