import { describe, expect, it } from 'vitest';
import { activePromoChips, EMPTY_PROMO_FILTERS } from './promoFilters';

describe('activePromoChips hay_mejores_ofertas', () => {
  it('adds a chip when the hay-mejores filter is on', () => {
    const chips = activePromoChips({ ...EMPTY_PROMO_FILTERS, hay_mejores_ofertas: '1' });
    expect(chips).toEqual([
      { id: 'hay_mejores', label: 'Hay mejores ofertas', remove: { hay_mejores_ofertas: '' } },
    ]);
  });

  it('omits the chip when the filter is off', () => {
    expect(activePromoChips(EMPTY_PROMO_FILTERS)).toEqual([]);
  });
});
