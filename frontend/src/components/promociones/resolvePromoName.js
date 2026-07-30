// Single source of truth for a promo's resolved NAME (used to build the
// filter universe and to match the filter predicate). Stops at
// name/payload.name and returns null for a genuinely unnamed promo, so the
// "(sin nombre)" grouping stays correct — it deliberately does NOT fall
// through to promotion_type/promotion_id, which are display-only fallbacks
// a renderer may still apply on top of this value.
export function resolvePromoName(promo) {
  return promo?.name || promo?.payload?.name || null;
}
