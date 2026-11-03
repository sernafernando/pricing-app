import { describe, it, expect } from 'vitest';
import {
  bestByMarkup,
  enrollBodyForPromo,
  listRowForPricelist,
  pickPonerPreciosPromos,
} from './pickPonerPreciosPromos';
import { LISTS } from '../../pricing/priceWrites';

describe('pickPonerPreciosPromos', () => {
  it('picks best SMART/DEAL and Premium of the month', () => {
    const picked = pickPonerPreciosPromos(
      [
        { promotion_id: 's1', promotion_type: 'SMART', status: 'candidate', nuestro_markup: 10 },
        { promotion_id: 's2', promotion_type: 'SMART', status: 'candidate', nuestro_markup: 22 },
        { promotion_id: 'd1', promotion_type: 'DEAL', status: 'candidate', nuestro_markup: 8 },
        {
          promotion_id: 'p1',
          promotion_type: 'SELLER_CAMPAIGN',
          status: 'candidate',
          name: 'PREMIUM NOVIEMBRE',
          nuestro_markup: 12,
        },
      ],
      { monthName: 'noviembre' },
    );
    expect(picked.smart.promotion_id).toBe('s2');
    expect(picked.deal.promotion_id).toBe('d1');
    expect(picked.premium.promotion_id).toBe('p1');
  });

  it('skips candidates without finite nuestro_markup', () => {
    expect(
      bestByMarkup([
        { promotion_id: 'null-first', promotion_type: 'SMART', status: 'candidate', nuestro_markup: null },
        { promotion_id: 'ok', promotion_type: 'SMART', status: 'candidate', nuestro_markup: 11 },
      ])?.promotion_id,
    ).toBe('ok');
    expect(
      bestByMarkup([
        { promotion_id: 'only-null', promotion_type: 'SMART', status: 'candidate', nuestro_markup: null },
      ]),
    ).toBeNull();
  });

  it('builds SMART and DEAL enroll bodies', () => {
    expect(
      enrollBodyForPromo({ promotion_id: 's', promotion_type: 'SMART', price: 900, nuestro_markup: 15 }),
    ).toEqual({
      promotion_id: 's',
      promotion_type: 'SMART',
      precio_visto: 900,
      markup_visto: 15,
    });
    expect(
      enrollBodyForPromo({
        promotion_id: 'd',
        promotion_type: 'DEAL',
        suggested_discounted_price: 800,
        min_discounted_price: 700,
        max_discounted_price: 900,
      }),
    ).toMatchObject({ deal_price: 800 });
  });

  it('maps pricelist ids to Lista ML rows', () => {
    expect(listRowForPricelist(4, LISTS)?.id).toBe('ml-clasica');
    expect(listRowForPricelist(17, LISTS)?.id).toBe('ml-3');
  });
});
