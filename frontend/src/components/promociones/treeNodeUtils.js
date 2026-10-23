// Shared helpers for the recursive `TreeNode` component and its callers
// (productos-catalog-family-tree PR3). Split out of TreeNode.jsx so
// react-refresh only sees component exports there.

import { isDeletedPublication } from '../publicacionesMl/publicationStatus';

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

/** An MLA-bearing node whose publication is deleted (`isDeletedPublication`). */
export function isDeletedNode(node) {
  return isMlaBearing(node.kind) && isDeletedPublication(node.publication_status, node.publication_sub_status);
}

// The filter hides an MLA-bearing node: matches_filter absent/null = show
// (fail-open); false = hidden unless revealAll.
function filterHides(node, filterActive, revealAll) {
  return filterActive && !revealAll && node.matches_filter === false;
}

// A deleted publication is hidden unless showDeleted, filter or not ("ver
// todos" reveals what the filter hid, never a deleted one). Grouping nodes
// have no matches_filter and are never hidden by this check directly —
// visibility for them is driven by their descendants (see
// `nodeHasVisibleContent`).
export function isNodeHidden(node, filterActive, revealAll, showDeleted = false) {
  if (!isMlaBearing(node.kind)) return false;
  if (!showDeleted && isDeletedNode(node)) return true;
  return filterHides(node, filterActive, revealAll);
}

/**
 * A node hidden ONLY for being deleted hands its children up a level (as a
 * hidden familia does): a deleted catalog must not take its live vinculadas
 * with it. A node the filter hides still takes its whole subtree.
 */
export function hoistsChildren(node, filterActive, revealAll, showDeleted = false) {
  return isMlaBearing(node.kind) && !showDeleted && isDeletedNode(node) && !filterHides(node, filterActive, revealAll);
}

// A grouping node renders only if at least one descendant MLA-bearing node is
// visible (or it has no MLA-bearing descendants at all, e.g. an empty/plain
// container — fail-open, never hide by default absent evidence). A node that
// hoists its children shows whatever they show.
export function nodeHasVisibleContent(node, filterActive, revealAll, showDeleted = false) {
  const children = node.children || [];
  if (hoistsChildren(node, filterActive, revealAll, showDeleted)) {
    return children.some((child) => nodeHasVisibleContent(child, filterActive, revealAll, showDeleted));
  }
  if (isMlaBearing(node.kind)) {
    return !isNodeHidden(node, filterActive, revealAll, showDeleted);
  }
  if (children.length === 0) return true;
  return children.some((child) => nodeHasVisibleContent(child, filterActive, revealAll, showDeleted));
}

/**
 * Counts every MLA-bearing descendant (inclusive) the filter hides
 * (`matches_filter === false`) and "ver todos" would reveal — a deleted one
 * only while deleted ones are shown — regardless of current reveal state:
 * sizes the root panel's "ver todos (N)" escape hatch.
 */
export function countHiddenDescendants(node, showDeleted = false) {
  // A hidden deleted node is not revealed, but its children are (`hoistsChildren`).
  const own = isMlaBearing(node.kind) && node.matches_filter === false && (showDeleted || !isDeletedNode(node));
  return (own ? 1 : 0) + (node.children || []).reduce((sum, child) => sum + countHiddenDescendants(child, showDeleted), 0);
}

/**
 * Counts every deleted MLA-bearing descendant (inclusive) the filter lets
 * through, under no node it hides (every one when the filter is off or
 * revealed), shown or not:
 * sizes "Ver eliminadas (N)", so the toggle shows exactly that many.
 */
export function countDeletedDescendants(node, filterActive = false, revealAll = false) {
  // A node the filter hides takes its subtree with it, deleted ones included.
  if (isNodeHidden(node, filterActive, revealAll, true)) return 0;
  const own = isDeletedNode(node);
  return (
    (own ? 1 : 0) +
    (node.children || []).reduce((sum, child) => sum + countDeletedDescendants(child, filterActive, revealAll), 0)
  );
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
