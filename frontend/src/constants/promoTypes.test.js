import { describe, it, expect } from 'vitest';
import { PROMO_TYPES } from './promoTypes';

describe('promoTypes', () => {
  it('exposes the 8 known promotion_type values with Spanish labels, in panel order', () => {
    expect(PROMO_TYPES).toEqual([
      { type: 'SELLER_CAMPAIGN', label: 'Campaña' },
      { type: 'DEAL', label: 'Deal' },
      { type: 'SMART', label: 'Smart' },
      { type: 'PRE_NEGOTIATED', label: 'Pre-negociada' },
      { type: 'PRICE_MATCHING', label: 'Igualación de precio' },
      { type: 'PRICE_DISCOUNT', label: 'Descuento' },
      { type: 'DOD', label: 'DOD' },
      { type: 'LIGHTNING', label: 'Lightning' },
    ]);
  });
});
