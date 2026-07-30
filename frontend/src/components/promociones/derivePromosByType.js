// Derives { [promotion_type]: string[] } (distinct display names, name === null
// for unnamed promos) from the already-fetched promos cache. Read at
// modal-open time — `promosCacheRef` is a plain ref (useLazyResource's
// cache), not reactive, so this is a snapshot, not a subscription.
export function derivePromosByType(promosCacheRef) {
  const byType = {};
  if (!promosCacheRef?.current) return byType;

  for (const entry of promosCacheRef.current.values()) {
    if (entry?.status !== 'ok') continue;
    const promotions = entry.data?.promotions || [];
    for (const promo of promotions) {
      const type = promo.promotion_type;
      if (!type) continue;
      if (!byType[type]) byType[type] = new Set();
      byType[type].add(promo.name ?? null);
    }
  }

  const result = {};
  for (const [type, names] of Object.entries(byType)) {
    result[type] = Array.from(names);
  }
  return result;
}
