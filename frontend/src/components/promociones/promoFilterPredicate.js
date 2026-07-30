// Pure predicate shared by every promo-list consumer so the type/name
// filter rule cannot be forked between components.
//
// - Empty selectedTypes => every type passes.
// - A type missing from selectedNames, or mapped to [], => every name of
//   that type passes.
// - The type-level filter always wins: a type excluded at the type level
//   is never shown regardless of a stale name selection for it.
export function matchesPromoFilter(promo, selectedTypes, selectedNames) {
  const typeOk = selectedTypes.length === 0 || selectedTypes.includes(promo.promotion_type);
  if (!typeOk) return false;

  const names = selectedNames[promo.promotion_type];
  const nameOk = !names || names.length === 0 || names.includes(promo.name ?? null);
  return nameOk;
}
