import { describe, it, expect } from 'vitest';
import {
  countDeletedDescendants,
  countHiddenDescendants,
  isDeletedNode,
  isFilterActive,
  isNodeHidden,
  nodeHasVisibleContent,
} from './treeNodeUtils';

describe('isFilterActive — every filter the backend folds into matches_filter', () => {
  it('is false when nothing narrows', () => {
    expect(isFilterActive([], 'disponible', null, null)).toBe(false);
    expect(isFilterActive(undefined, undefined, undefined, undefined)).toBe(false);
  });

  it('is true for the promo and store filters (unchanged)', () => {
    expect(isFilterActive(['SMART'], 'disponible', null, null)).toBe(true);
    expect(isFilterActive([], 'aplicada', null, null)).toBe(true);
    expect(isFilterActive([], 'disponible', '2645', null)).toBe(true);
  });

  it('is true for the wholesale (PxQ) filter on its own', () => {
    // The backend marks matches_filter:false for publications with no tiers.
    // If this returns false, the UI renders exactly those nodes anyway — the
    // way the store filter once "silently did nothing".
    expect(isFilterActive([], 'disponible', null, 'con_pxq')).toBe(true);
  });

  it('hides an MLA node the backend excluded once PxQ alone is active', () => {
    const node = { kind: 'publicacion', mla: 'MLA1', matches_filter: false };
    const active = isFilterActive([], 'disponible', null, 'con_pxq');
    expect(isNodeHidden(node, active, false)).toBe(true);
  });

  it('accepts the boolean form of the PxQ filter too', () => {
    expect(isFilterActive([], 'disponible', null, true)).toBe(true);
    expect(isFilterActive([], 'disponible', null, false)).toBe(false);
  });
});

describe('deleted publications — hidden unless showDeleted', () => {
  const live = { kind: 'publicacion', mla: 'MLA1', publication_status: 'active', publication_sub_status: null };
  const gone = { kind: 'publicacion', mla: 'MLA2', publication_status: 'gone' };
  const deletedInMl = { kind: 'vinculada', mla: 'MLA3', publication_status: 'inactive', publication_sub_status: ['forbidden', 'deleted'] };
  const noMlData = { kind: 'catalogo', mla: 'MLA4', publication_status: 'no_ml_data' };

  it('is deleted when it vanished from ML or ML marks it deleted in sub_status', () => {
    expect(isDeletedNode(gone)).toBe(true);
    expect(isDeletedNode(deletedInMl)).toBe(true);
    expect(isDeletedNode(live)).toBe(false);
    expect(isDeletedNode(noMlData)).toBe(false);
    expect(isDeletedNode({ kind: 'familia', publication_status: 'gone' })).toBe(false);
  });

  it('hides a deleted node with no filter active, and shows it with showDeleted', () => {
    expect(isNodeHidden(deletedInMl, false, false)).toBe(true);
    expect(isNodeHidden(gone, false, false, false)).toBe(true);
    expect(isNodeHidden(gone, false, false, true)).toBe(false);
    expect(isNodeHidden(live, false, false)).toBe(false);
  });

  it('"ver todos" reveals what the filter hid, never a deleted node', () => {
    expect(isNodeHidden({ ...gone, matches_filter: true }, true, true)).toBe(true);
    expect(isNodeHidden({ ...live, matches_filter: false }, true, true)).toBe(false);
  });

  it('a showDeleted node still obeys the filter', () => {
    expect(isNodeHidden({ ...gone, matches_filter: false }, true, false, true)).toBe(true);
  });

  it('a grouping node whose only publications are deleted has nothing to show', () => {
    const familia = { kind: 'familia', children: [gone, deletedInMl] };
    expect(nodeHasVisibleContent(familia, false, false)).toBe(false);
    expect(nodeHasVisibleContent(familia, false, false, true)).toBe(true);
    expect(nodeHasVisibleContent({ kind: 'familia', children: [gone, live] }, false, false)).toBe(true);
  });

  it('counts the deleted publications at any depth', () => {
    expect(countDeletedDescendants({ kind: 'familia', children: [gone, { kind: 'familia', children: [deletedInMl, live] }] })).toBe(2);
    expect(countDeletedDescendants(live)).toBe(0);
  });

  // Each count is what its button then shows: a filter and the deleted toggle must not promise each other's nodes.
  it('"Ver eliminadas (N)" counts only the deleted ones the filter lets through', () => {
    const tree = { kind: 'familia', children: [{ ...gone, matches_filter: false }, { ...deletedInMl, matches_filter: true }] };
    expect(countDeletedDescendants(tree, true, false)).toBe(1);
    expect(countDeletedDescendants(tree, true, true)).toBe(2); // "ver todos" lifts the filter
    expect(countDeletedDescendants(tree, false, false)).toBe(2);
  });

  it('"ver todos (N)" counts only the filtered-out nodes it would reveal', () => {
    const tree = { kind: 'familia', children: [{ ...gone, matches_filter: false }, { ...live, matches_filter: false }] };
    expect(countHiddenDescendants(tree)).toBe(1);
    expect(countHiddenDescendants(tree, true)).toBe(2); // deleted ones shown: "ver todos" reveals them too
  });
});
