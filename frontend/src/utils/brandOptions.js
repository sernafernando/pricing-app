/**
 * Brand option lists come from the server already narrowed to visible brands (with stock, or in the
 * admin exception list). A URL, saved filter or edited record can still name a brand that is now
 * hidden: it must stay rendered and selectable. These helpers add those selected brands back.
 */

const key = (value) => String(value ?? '').trim().toLowerCase();

const asList = (value) => {
  if (Array.isArray(value)) return value;
  if (value === null || value === undefined || value === '') return [];
  return [value];
};

/**
 * Server options plus every selected brand missing from them, compared case-insensitively.
 * Server order is kept and the missing selected brands are appended in selection order.
 * Returns `options` itself when nothing is missing, so memoized consumers keep a stable reference.
 *
 * @param {string[] | null | undefined} options  brand names from the server
 * @param {string | string[] | null | undefined} selected  the selected brand(s)
 * @returns {string[]}
 */
export function withSelectedBrands(options, selected) {
  const list = Array.isArray(options) ? options : [];
  const known = new Set(list.map(key));
  const missing = [];
  for (const brand of asList(selected)) {
    const k = key(brand);
    if (!k || known.has(k)) continue;
    known.add(k);
    missing.push(brand);
  }
  return missing.length ? [...list, ...missing] : list;
}

/**
 * Brands of `candidates` that are also in `visible` (case-insensitive), plus the selected ones.
 * `visible === null` means "unknown" (the visibility list failed to load): every candidate is kept.
 *
 * @param {string[]} candidates  brand names found in the data
 * @param {string[] | null} visible  visible brand names from the server, or null when unknown
 * @param {string | string[] | null | undefined} selected
 * @returns {string[]}
 */
export function visibleBrands(candidates, visible, selected) {
  const list = Array.isArray(candidates) ? candidates : [];
  if (visible === null || visible === undefined) return withSelectedBrands(list, selected);
  const allowed = new Set(visible.map(key));
  return withSelectedBrands(list.filter((brand) => allowed.has(key(brand))), selected);
}
