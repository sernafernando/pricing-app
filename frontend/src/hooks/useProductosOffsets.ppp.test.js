import { describe, it, expect } from 'vitest';
import { formatPppMonto, formatPppFecha } from './useProductosOffsets';

describe('formatPppMonto — PPP markup formatter', () => {
  it('returns null for null/undefined value (caller decides the no-data fallback)', () => {
    expect(formatPppMonto(null, 'pvp_clasica')).toBeNull();
    expect(formatPppMonto(undefined, 'pvp_clasica')).toBeNull();
  });

  it('formats an already-percent key as-is', () => {
    expect(formatPppMonto(32.5, 'pvp_clasica')).toBe('32.50%');
    expect(formatPppMonto(-4.2, 'cuota_clasica_3')).toBe('-4.20%');
  });

  it('scales the raw-ratio mejor_oferta key by x100', () => {
    expect(formatPppMonto(0.612, 'mejor_oferta')).toBe('61.20%');
  });

  it('treats 0 as a real value, not missing', () => {
    expect(formatPppMonto(0, 'pvp_clasica')).toBe('0.00%');
  });
});

describe('formatPppFecha — PPP source date formatter', () => {
  it('formats as dd/mm/aa', () => {
    expect(formatPppFecha('2026-07-15')).toBe('15/07/26');
  });

  it('always renders regardless of age — no relative wording, no staleness gate', () => {
    expect(formatPppFecha('2020-01-01')).toBe('01/01/20');
  });

  it('returns null for missing/invalid input', () => {
    expect(formatPppFecha(null)).toBeNull();
    expect(formatPppFecha(undefined)).toBeNull();
    expect(formatPppFecha('not-a-date')).toBeNull();
  });
});
