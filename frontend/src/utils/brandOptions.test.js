import { describe, it, expect } from 'vitest';
import { withSelectedBrands, visibleBrands } from './brandOptions';

describe('withSelectedBrands', () => {
  it('appends a selected brand missing from the server list, keeping the server order', () => {
    expect(withSelectedBrands(['HP', 'TP-LINK'], ['OCULTA'])).toEqual(['HP', 'TP-LINK', 'OCULTA']);
  });

  it('does not add brands that are not selected', () => {
    expect(withSelectedBrands(['HP'], [])).toEqual(['HP']);
    expect(withSelectedBrands(['HP'], null)).toEqual(['HP']);
  });

  it('compares case-insensitively and does not duplicate', () => {
    expect(withSelectedBrands(['HP', 'TP-Link'], ['tp-link', 'hp'])).toEqual(['HP', 'TP-Link']);
    expect(withSelectedBrands([], ['OCULTA', 'oculta'])).toEqual(['OCULTA']);
  });

  it('accepts a single selected value and ignores empty ones', () => {
    expect(withSelectedBrands(['HP'], 'OCULTA')).toEqual(['HP', 'OCULTA']);
    expect(withSelectedBrands(['HP'], '')).toEqual(['HP']);
    expect(withSelectedBrands(undefined, ['OCULTA'])).toEqual(['OCULTA']);
  });

  it('returns the same array when nothing is missing', () => {
    const options = ['HP'];
    expect(withSelectedBrands(options, ['HP'])).toBe(options);
  });
});

describe('visibleBrands', () => {
  it('keeps only candidates the server lists as visible, plus the selected ones', () => {
    expect(visibleBrands(['A', 'B', 'C'], ['a', 'C'], [])).toEqual(['A', 'C']);
    expect(visibleBrands(['A', 'B', 'C'], ['A'], ['B'])).toEqual(['A', 'B']);
  });

  it('keeps every candidate when visibility is unknown', () => {
    expect(visibleBrands(['A', 'B'], null, [])).toEqual(['A', 'B']);
  });
});
