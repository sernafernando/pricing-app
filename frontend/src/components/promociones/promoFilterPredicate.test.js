import { describe, it, expect } from 'vitest';
import { matchesPromoFilter } from './promoFilterPredicate';

const dealPromo = { promotion_type: 'DEAL', name: '2x1' };
const smartPromo = { promotion_type: 'SMART', name: 'Promo Smart' };
const noNamePromo = { promotion_type: 'DEAL', name: null };

describe('matchesPromoFilter', () => {
  it('matches everything when both selectedTypes and selectedNames are empty', () => {
    expect(matchesPromoFilter(dealPromo, [], {})).toBe(true);
    expect(matchesPromoFilter(smartPromo, [], {})).toBe(true);
  });

  it('type filter wins: excluded type never matches regardless of name selection', () => {
    expect(matchesPromoFilter(dealPromo, ['SMART'], { DEAL: ['2x1'] })).toBe(false);
  });

  it('type included, no name narrowing for that type -> matches every name', () => {
    expect(matchesPromoFilter(dealPromo, ['DEAL'], {})).toBe(true);
  });

  it('type included, name narrowing active and matching -> matches', () => {
    expect(matchesPromoFilter(dealPromo, ['DEAL'], { DEAL: ['2x1'] })).toBe(true);
  });

  it('type included, name narrowing active but not matching -> excluded', () => {
    expect(matchesPromoFilter(dealPromo, ['DEAL'], { DEAL: ['3x2'] })).toBe(false);
  });

  it('name narrowing for one type does not affect another type', () => {
    expect(matchesPromoFilter(smartPromo, [], { DEAL: ['2x1'] })).toBe(true);
  });

  it('null-name promo is selectable via the null sentinel', () => {
    expect(matchesPromoFilter(noNamePromo, [], { DEAL: [null] })).toBe(true);
    expect(matchesPromoFilter(noNamePromo, [], { DEAL: ['2x1'] })).toBe(false);
  });

  it('matches by payload.name when the top-level name is absent', () => {
    const payloadNamedPromo = { promotion_type: 'SELLER_CAMPAIGN', name: null, payload: { name: 'PREMIUM JULIO' } };
    expect(matchesPromoFilter(payloadNamedPromo, [], { SELLER_CAMPAIGN: ['PREMIUM JULIO'] })).toBe(true);
  });
});
