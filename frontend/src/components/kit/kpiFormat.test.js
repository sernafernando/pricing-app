import { describe, it, expect } from 'vitest';
import { formatInt, formatOtherCurrencies, formatPct } from './kpiFormat';

describe('kpiFormat', () => {
  it('formats counts the es-AR way, a missing count as 0', () => {
    expect(formatInt(1284)).toBe('1.284');
    expect(formatInt(undefined)).toBe('0');
  });

  it('formats a percentage with one decimal, unknown as a dash', () => {
    expect(formatPct(26.34)).toBe('26,3%');
    expect(formatPct(null)).toBe('—');
    expect(formatPct(undefined)).toBe('—');
  });

  it('lists other currencies apart, never added to pesos', () => {
    expect(formatOtherCurrencies({ USD: 1500.5 })).toBe('1.500,50 USD');
    expect(formatOtherCurrencies({})).toBeNull();
    expect(formatOtherCurrencies(null)).toBeNull();
  });
});
