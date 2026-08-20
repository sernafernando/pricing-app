import { describe, it, expect } from 'vitest';
import { formatMoney } from './formatMoney';

describe('formatMoney', () => {
  it('formats a float with binary-representation noise to two decimals, es-AR separators', () => {
    expect(formatMoney(13937.999999999998)).toBe('$ 13.938,00');
  });

  it('formats a clean value with thousands separator and comma decimals', () => {
    expect(formatMoney(38762.5)).toBe('$ 38.762,50');
  });

  it('returns null for null/undefined/empty-string input (caller decides the placeholder)', () => {
    expect(formatMoney(null)).toBeNull();
    expect(formatMoney(undefined)).toBeNull();
    expect(formatMoney('')).toBeNull();
  });

  it('returns null for non-numeric input instead of throwing', () => {
    expect(formatMoney('abc')).toBeNull();
  });
});
