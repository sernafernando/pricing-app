import { describe, it, expect } from 'vitest';
import { isTpSolo, onlyFacetStoreChips } from './tpMode';

describe('isTpSolo', () => {
  it('is true only when the explicit permission list carries tplink.solo', () => {
    expect(isTpSolo(['ml_ops.ver', 'tplink.solo'])).toBe(true);
    expect(isTpSolo(['ml_ops.ver', 'tplink.tema'])).toBe(false);
    expect(isTpSolo([])).toBe(false);
    expect(isTpSolo(undefined)).toBe(false);
  });
});

describe('onlyFacetStoreChips', () => {
  const chips = {
    options: ['57997', '2645,471846', 'sin_tienda'],
    labels: { 57997: 'Gauss', '2645,471846': 'TP-Link', sin_tienda: 'Sin tienda' },
    counts: { 57997: 0, '2645,471846': 3, sin_tienda: 0 },
    activeValue: '',
  };

  it('keeps only the chips whose stores the facet returned', () => {
    const result = onlyFacetStoreChips(chips, { 2645: 2, 471846: 1 });
    expect(result.options).toEqual(['2645,471846']);
    expect(result.labels['2645,471846']).toBe('TP-Link');
    expect(result.counts['2645,471846']).toBe(3);
  });

  it('keeps the active chip so the current filter stays visible', () => {
    const result = onlyFacetStoreChips({ ...chips, activeValue: '57997' }, { 2645: 2 });
    expect(result.options).toEqual(['57997', '2645,471846']);
  });

  it('offers no chip when the facet is empty', () => {
    expect(onlyFacetStoreChips(chips, {}).options).toEqual([]);
  });
});
