import { describe, it, expect } from 'vitest';
import { STORE_FILTER_LABELS, STORE_NONE, storeFilterChips } from './tiendasOficiales';

describe('storeFilterChips', () => {
  it('keeps the known stores, in their order, even at zero', () => {
    const { options } = storeFilterChips({ 57997: 3 });
    expect(options).toEqual(['57997', '2645', '144', '191942', STORE_NONE]);
  });

  it('adds a chip for any other store the facet reports, before "Sin tienda", ids ascending', () => {
    const { options, labels } = storeFilterChips({ 57997: 3, 900001: 1, 31: 2, sin_tienda: 1 });
    expect(options).toEqual(['57997', '2645', '144', '191942', '31', '900001', STORE_NONE]);
    expect(labels['900001']).toBe('Tienda 900001');
    expect(labels['31']).toBe('Tienda 31');
    expect(labels['57997']).toBe(STORE_FILTER_LABELS[57997]);
  });

  it('keeps the selected store as a chip even when the facet no longer reports it', () => {
    const { options, labels } = storeFilterChips({}, '424242');
    expect(options).toContain('424242');
    expect(labels['424242']).toBe('Tienda 424242');
  });
});
