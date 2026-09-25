import { describe, it, expect } from 'vitest';
import { Laptop, Smartphone, Package, Watch, Monitor } from 'lucide-react';
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

  // Minor fix: `/MONITOR|TV/` matched "TV" ANYWHERE in the string — a
  // category containing those two letters in the middle of another word
  // (e.g. a future "ACTIVACION" or "CREATIVIDAD") would silently get the
  // monitor icon. Only a real standalone "TV" token should match.
  it('does not match "TV" as a substring of an unrelated word', () => {
    expect(getCategoryIcon('CREATVX FUTURA')).not.toBe(Monitor);
  });

  it('still matches a standalone "TV" token', () => {
    expect(getCategoryIcon('MONITORES Y TV STICKS')).toBe(Monitor);
  });
});
