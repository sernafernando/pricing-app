// The price a promo row SHOWS. Single source for the panel (what the
// operator sees) and the apply control (what it sends as `precio_visto`), so
// the backend's price guard compares against exactly what was on screen.
//
// `price` is 0 for candidate promos of some types; fall back to the
// suggested discounted price so the row shows the price it WOULD apply at.
export function promoDisplayPrice(promo) {
  if (!promo) return null;
  if (promo.price > 0) return promo.price;
  return promo.suggested_discounted_price ?? null;
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
