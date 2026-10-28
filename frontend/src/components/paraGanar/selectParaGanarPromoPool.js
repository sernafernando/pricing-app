import { ML_PRICED_TYPES } from '../promociones/promoDisplayPrice';

/** Seller-priced promos that take an explicit deal_price (not ML-priced SMART). */
export const SELLER_PRICED_TYPES = new Set(['DEAL', 'SELLER_CAMPAIGN']);

function isCandidate(promo) {
  return promo?.status === 'candidate';
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

/**
 * PARA GANAR pool (D18): prefer SMART-like candidates; else DEAL/SELLER_CAMPAIGN
 * whose discounted range can hit precio_sugerido (criteria bridge).
 *
 * @param {Array<object>} promotions
 * @param {{ precioSugerido?: number|null }} [opts]
 * @returns {Array<object>}
 */
export function selectParaGanarPromoPool(promotions, { precioSugerido = null } = {}) {
  const list = Array.isArray(promotions) ? promotions : [];
  const candidates = list.filter(isCandidate);

  const smartLike = candidates.filter((p) => ML_PRICED_TYPES.has(p.promotion_type));
  if (smartLike.length > 0) {
    return [...smartLike].sort((a, b) =>
      String(a.name || a.promotion_id || '').localeCompare(String(b.name || b.promotion_id || '')),
    );
  }

  const sellerPriced = candidates
    .filter((p) => SELLER_PRICED_TYPES.has(p.promotion_type))
    .filter((p) => inDealRange(p, precioSugerido));

  return [...sellerPriced].sort((a, b) =>
    String(a.name || a.promotion_id || '').localeCompare(String(b.name || b.promotion_id || '')),
  );
}
