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
 * True when the active promo filter (`promoTipos`/`promoEstado`) is actually
 * narrowing results — mirrors `ProductoMLAsPanel`'s `buildPromoFilterParams`
 * activation rule (types present, or estado != the 'disponible' no-op default).
 */
export function isFilterActive(promoTipos, promoEstado) {
  const tipos = promoTipos || [];
  const estado = promoEstado || 'disponible';
  return tipos.length > 0 || estado !== 'disponible';
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
