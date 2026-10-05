function positiveNumber(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

// The price a promo row SHOWS — the ONE offer-price rule, mirrored exactly
// by the backend's `precio_de_oferta` (ml_promotions_pricing.py), which the
// pre-apply guard, the 409's `precio_actual` and every markup use. The apply
// control sends this value as `precio_visto`, so the guard compares like
// with like: `price` when > 0, else `suggested_discounted_price` when > 0,
// else null.
//
// `price` is legitimately 0 for candidate SELLER_CAMPAIGN/DEAL rows (the
// seller sets the price; ML only suggests one). ML-priced types normally
// carry ML's offer in `price` even as candidates.
export function promoDisplayPrice(promo) {
  if (!promo) return null;
  return positiveNumber(promo.price) ?? positiveNumber(promo.suggested_discounted_price);
}

// ML sets the offer price for these (the operator only accepts it), and ML
// recalculates candidates daily. Applying them requires the seen price; the
// backend refuses to enroll if ML's live offer moved (incident 2026-10-05).
export const ML_PRICED_TYPES = new Set(['SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING']);

// How old a timestamp is, in words ("recién", "hace 2 min", "hace 3 h",
// "hace 2 d"). A future timestamp is clock skew, never a negative age:
// "recién". Unusable input returns null so the caller says nothing.
export function formatRelativeAge(timestamp, now = Date.now()) {
  if (!timestamp) return null;
  const ts = Date.parse(timestamp);
  if (Number.isNaN(ts)) return null;

  const seconds = Math.floor((now - ts) / 1000);
  if (seconds < 60) return 'recién';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.floor(hours / 24)} d`;
}
