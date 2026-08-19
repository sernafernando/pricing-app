import { describe, it, expect } from 'vitest';
import { isFilterActive, isNodeHidden } from './treeNodeUtils';

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
