import { describe, it, expect } from 'vitest';
import { formatRelativeAge, promoDisplayPrice } from './promoDisplayPrice';

// Mirrors backend `precio_de_oferta` (ml_promotions_pricing.py): the panel
// shows this price, sends it as `precio_visto`, and the guard compares it
// with the SAME rule applied to ML's live offer. Same fallback order, same
// "> 0" test on both fields — any drift makes the guard reject good applies.
describe('promoDisplayPrice — the one offer-price rule', () => {
  it('price wins when positive', () => {
    expect(promoDisplayPrice({ price: 100, suggested_discounted_price: 90 })).toBe(100);
  });

  it('falls back to the suggested price when price is 0', () => {
    expect(promoDisplayPrice({ price: 0, suggested_discounted_price: 90 })).toBe(90);
  });

  it.each([
    [{}],
    [{ price: 0 }],
    [{ price: null, suggested_discounted_price: null }],
    [{ price: 0, suggested_discounted_price: 0 }],
    [{ price: -5, suggested_discounted_price: -1 }],
  ])('is null when neither is usable (%j)', (promo) => {
    expect(promoDisplayPrice(promo)).toBeNull();
  });

  it('accepts numeric strings like the backend does', () => {
    expect(promoDisplayPrice({ price: '372408.72' })).toBe(372408.72);
  });
});

describe('formatRelativeAge', () => {
  const now = Date.parse('2026-10-05T15:00:00Z');

  it('collapses future timestamps (clock skew) to "recién"', () => {
    expect(formatRelativeAge('2026-10-05T15:05:00Z', now)).toBe('recién');
  });

  it('reads days', () => {
    expect(formatRelativeAge('2026-10-03T15:00:00Z', now)).toBe('hace 2 d');
  });

  it('is null for unusable input', () => {
    expect(formatRelativeAge('not a date', now)).toBeNull();
  });
});
