import { describe, it, expect } from 'vitest';
import { Laptop, Smartphone, Package, Watch } from 'lucide-react';
import { getCategoryIcon } from './categoryIcon';

// ventas-ml-rediseno PR14.T5 (LISTING R28): `item_category` is free-text
// Spanish ERP data (`productos_erp.categoria`, verified live: "NOTEBOOK",
// "CELULAR, TABLET y EBOOK", "SMARTWATCHS", ...) — never an enum, so the
// lookup matches by keyword, not exact equality.
describe('getCategoryIcon', () => {
  it('maps a known category keyword to its icon component', () => {
    expect(getCategoryIcon('NOTEBOOK')).toBe(Laptop);
  });

  it('matches case-insensitively and by substring', () => {
    expect(getCategoryIcon('celular, tablet y ebook')).toBe(Smartphone);
    expect(getCategoryIcon('SMARTWATCHS')).toBe(Watch);
  });

  it('falls back to Package for an unmapped category', () => {
    expect(getCategoryIcon('UNA CATEGORIA INEXISTENTE')).toBe(Package);
  });

  it('falls back to Package for null/undefined/empty category', () => {
    expect(getCategoryIcon(null)).toBe(Package);
    expect(getCategoryIcon(undefined)).toBe(Package);
    expect(getCategoryIcon('')).toBe(Package);
  });
});
