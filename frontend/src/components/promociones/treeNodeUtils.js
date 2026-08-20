// Shared helpers for the recursive `TreeNode` component and its callers
// (productos-catalog-family-tree PR3). Split out of TreeNode.jsx so
// react-refresh only sees component exports there.

// Grouping nodes (no `mla`, no own promos) vs MLA-bearing nodes (carry `mla`
// + optional `matches_filter`, get their own promos sub-spoiler). Mirrors
// `TreeNode.kind` from `backend/app/schemas/productos_tree.py`.
const MLA_BEARING_KINDS = new Set(['catalogo', 'vinculada', 'publicacion']);

export function isMlaBearing(kind) {
  return MLA_BEARING_KINDS.has(kind);
}

/**
 * True when ANY tree-level filter is actually narrowing results.
 *
 * Must cover every filter the backend folds into `matches_filter`, because
 * that is the flag `isNodeHidden` gates on and the backend composes them all
 * with AND (`_compose_matches` in `productos_detail.py`) rather than dropping
 * nodes. A filter missing here means the backend correctly marks a node
 * `matches_filter: false` and the UI renders it anyway — which is exactly how
 * the official-store filter silently did nothing when no promo filter was
 * also active (the default, and most common, case).
 *
 * - promo: types present, or estado != the 'disponible' no-op default
 *   (mirrors `ProductoMLAsPanel`'s `buildPromoFilterParams` activation rule)
 * - official store: any store selected
 * - wholesale (PxQ): the filter is on ('con_pxq' or true). Truthiness is the
 *   test on purpose, so the page's `'con_pxq'` string and a plain boolean
 *   both count — a filter that is on must never depend on which of the two
 *   shapes reached this function.
 */
export function isFilterActive(promoTipos, promoEstado, tiendaOficial, conPxq) {
  const tipos = promoTipos || [];
  const estado = promoEstado || 'disponible';
  return tipos.length > 0 || estado !== 'disponible' || Boolean(tiendaOficial) || Boolean(conPxq);
}

// matches_filter absent/null = show (fail-open); false = hidden unless
// revealAll. Grouping nodes have no matches_filter and are never hidden by
// this check directly — visibility for them is driven by their descendants
// (see `nodeHasVisibleContent`).
export function isNodeHidden(node, filterActive, revealAll) {
  if (!isMlaBearing(node.kind)) return false;
  if (!filterActive || revealAll) return false;
  return node.matches_filter === false;
}

// A grouping node renders only if at least one descendant MLA-bearing node is
// visible (or it has no MLA-bearing descendants at all, e.g. an empty/plain
// container — fail-open, never hide by default absent evidence).
export function nodeHasVisibleContent(node, filterActive, revealAll) {
  if (isMlaBearing(node.kind)) {
    return !isNodeHidden(node, filterActive, revealAll);
  }
  const children = node.children || [];
  if (children.length === 0) return true;
  return children.some((child) => nodeHasVisibleContent(child, filterActive, revealAll));
}

/**
 * Counts every MLA-bearing descendant (inclusive) whose `matches_filter` is
 * explicitly `false`, regardless of current reveal state — used by the root
 * panel to size the "ver todos (N)" escape hatch.
 */
export function countHiddenDescendants(node) {
  let count = isMlaBearing(node.kind) && node.matches_filter === false ? 1 : 0;
  (node.children || []).forEach((child) => {
    count += countHiddenDescendants(child);
  });
  return count;
}

const CHILD_KIND_PLURAL = {
  catalogo: ['catálogo', 'catálogos'],
  vinculada: ['vinculada', 'vinculadas'],
  publicacion: ['publicación', 'publicaciones'],
  familia: ['familia', 'familias'],
};

/**
 * FE-only, no backend involved: summarizes a grouping node's DIRECT children
 * by `kind` (e.g. "2 catálogos · 1 vinculada"), purely cosmetic context for a
 * collapsed familia/catalogo node. Returns '' when there are no children
 * (nothing to summarize).
 */
export function describeChildKinds(children) {
  if (!children || children.length === 0) return '';
  const counts = new Map();
  children.forEach((child) => {
    counts.set(child.kind, (counts.get(child.kind) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([kind, count]) => {
      const [singular, plural] = CHILD_KIND_PLURAL[kind] || [kind, kind];
      return `${count} ${count === 1 ? singular : plural}`;
    })
    .join(' · ');
}
