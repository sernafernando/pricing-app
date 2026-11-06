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

  // Captured DEAL, MLA1506729443 "MKP T1 CYBER MONDAY NOV" (2026-11-06): ML's web proposes it at its
  // max, the smallest discount ML accepts. Same cases as backend TestPrecioDeOferta.
  const capturedDeal = {
    promotion_id: 'P-MLA18145042',
    promotion_type: 'DEAL',
    price: 0,
    status: 'candidate',
    original_price: 86539,
    max_discounted_price: 57920.55,
    min_discounted_price: 17307.81,
    suggested_discounted_price: 49266.65,
  };

  it('uses the max for a candidate DEAL', () => {
    expect(promoDisplayPrice(capturedDeal)).toBe(57920.55);
  });

  it('falls back to the suggested for a DEAL without max', () => {
    expect(promoDisplayPrice({ ...capturedDeal, max_discounted_price: null })).toBe(49266.65);
  });

  it('keeps the price of a DEAL that has one', () => {
    expect(promoDisplayPrice({ ...capturedDeal, price: 55000 })).toBe(55000);
  });

  it('keeps the suggested for SELLER_CAMPAIGN', () => {
    expect(promoDisplayPrice({ ...capturedDeal, promotion_type: 'SELLER_CAMPAIGN' })).toBe(49266.65);
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
