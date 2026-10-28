import { describe, expect, it } from 'vitest';
import { selectParaGanarPromoPool } from './selectParaGanarPromoPool';

describe('selectParaGanarPromoPool', () => {
  it('prefers SMART candidates over DEAL even when DEAL fits the range', () => {
    const pool = selectParaGanarPromoPool(
      [
        {
          promotion_id: 'D1',
          promotion_type: 'DEAL',
          status: 'candidate',
          name: 'Deal',
          min_discounted_price: 100,
          max_discounted_price: 200,
        },
        {
          promotion_id: 'S1',
          promotion_type: 'SMART',
          status: 'candidate',
          name: 'Smart',
          price: 150,
        },
      ],
      { precioSugerido: 150 },
    );
    expect(pool.map((p) => p.promotion_id)).toEqual(['S1']);
  });

  it('falls back to DEAL/SELLER_CAMPAIGN in suggested-price range', () => {
    const pool = selectParaGanarPromoPool(
      [
        {
          promotion_id: 'D-in',
          promotion_type: 'DEAL',
          status: 'candidate',
          name: 'In range',
          min_discounted_price: 100,
          max_discounted_price: 200,
        },
        {
          promotion_id: 'D-out',
          promotion_type: 'SELLER_CAMPAIGN',
          status: 'candidate',
          name: 'Out',
          min_discounted_price: 300,
          max_discounted_price: 400,
        },
        {
          promotion_id: 'D-started',
          promotion_type: 'DEAL',
          status: 'started',
          name: 'Already on',
          min_discounted_price: 100,
          max_discounted_price: 200,
        },
      ],
      { precioSugerido: 150 },
    );
    expect(pool.map((p) => p.promotion_id)).toEqual(['D-in']);
  });

  it('ignores non-writable types', () => {
    const pool = selectParaGanarPromoPool(
      [{ promotion_id: 'X', promotion_type: 'DOD', status: 'candidate', name: 'DOD' }],
      { precioSugerido: 10 },
    );
    expect(pool).toEqual([]);
  });
});
