import { describe, expect, it } from 'vitest';
import { isPremiumPromo, selectParaGanarPromoPool } from './selectParaGanarPromoPool';

describe('isPremiumPromo', () => {
  it('matches PREMIUM + month style names', () => {
    expect(isPremiumPromo({ name: 'PREMIUM JULIO' })).toBe(true);
    expect(isPremiumPromo({ name: null, payload: { name: 'Premium Agosto' } })).toBe(true);
    expect(isPremiumPromo({ name: 'Deal 2x1' })).toBe(false);
  });
});

describe('selectParaGanarPromoPool', () => {
  it('takes one SMART, one other, and reserves Premium last', () => {
    const pool = selectParaGanarPromoPool(
      [
        {
          promotion_id: 'P1',
          promotion_type: 'SELLER_CAMPAIGN',
          status: 'candidate',
          name: 'PREMIUM JULIO',
          min_discounted_price: 100,
          max_discounted_price: 200,
        },
        {
          promotion_id: 'D1',
          promotion_type: 'DEAL',
          status: 'candidate',
          name: 'OFERTAS OCTUBRE',
          min_discounted_price: 140,
          max_discounted_price: 160,
        },
        {
          promotion_id: 'D-lyonn',
          promotion_type: 'SELLER_CAMPAIGN',
          status: 'candidate',
          name: 'A PVP LYONN',
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
    expect(pool.map((p) => p.promotion_id)).toEqual(['S1', 'D1', 'P1']);
    expect(pool.map((p) => p.pool_slot)).toEqual(['Mejor', 'Intermedia', 'Tercera']);
  });

  it('still shows Premium last and only one non-Premium DEAL when several fit', () => {
    const pool = selectParaGanarPromoPool(
      [
        {
          promotion_id: 'P1',
          promotion_type: 'SELLER_CAMPAIGN',
          status: 'candidate',
          name: 'PREMIUM JULIO',
          min_discounted_price: 100,
          max_discounted_price: 200,
        },
        {
          promotion_id: 'D1',
          promotion_type: 'DEAL',
          status: 'candidate',
          name: 'OFERTAS',
          min_discounted_price: 145,
          max_discounted_price: 155,
        },
        {
          promotion_id: 'D2',
          promotion_type: 'SELLER_CAMPAIGN',
          status: 'candidate',
          name: 'A PVP TP',
          min_discounted_price: 50,
          max_discounted_price: 250,
        },
      ],
      { precioSugerido: 150 },
    );
    expect(pool.map((p) => p.promotion_id)).toEqual(['D1', 'P1']);
    expect(pool).toHaveLength(2);
  });

  it('puts Premium second when only SMART + Premium fit', () => {
    const pool = selectParaGanarPromoPool(
      [
        {
          promotion_id: 'P1',
          promotion_type: 'SELLER_CAMPAIGN',
          status: 'candidate',
          name: 'PREMIUM JULIO',
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
    expect(pool.map((p) => p.promotion_id)).toEqual(['S1', 'P1']);
  });

  it('shows started Premium as applied when no candidate Premium exists', () => {
    const pool = selectParaGanarPromoPool(
      [
        {
          promotion_id: 'P-on',
          promotion_type: 'SELLER_CAMPAIGN',
          status: 'started',
          name: 'PREMIUM OCTUBRE',
          price: 1699256,
          nuestro_markup: 9.3,
        },
        {
          promotion_id: 'D1',
          promotion_type: 'DEAL',
          status: 'candidate',
          name: 'OFERTAS OCTUBRE',
          min_discounted_price: 500000,
          max_discounted_price: 2300000,
          nuestro_markup: 9.3,
        },
      ],
      { precioSugerido: 1740385, markupMin: 9, markupMax: 19 },
    );
    expect(pool.map((p) => p.promotion_id)).toEqual(['D1', 'P-on']);
    expect(pool[1].pool_applied).toBe(true);
    expect(pool[0].pool_applied).toBe(false);
  });

  it('drops DEAL outside suggested range and started rows', () => {
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

  it('filters by markup band when nuestro_markup is present', () => {
    const pool = selectParaGanarPromoPool(
      [
        {
          promotion_id: 'S-low',
          promotion_type: 'SMART',
          status: 'candidate',
          name: 'Low markup',
          price: 150,
          nuestro_markup: 2,
        },
        {
          promotion_id: 'S-ok',
          promotion_type: 'SMART',
          status: 'candidate',
          name: 'Ok markup',
          price: 151,
          nuestro_markup: 8,
        },
      ],
      { precioSugerido: 150, markupMin: 5, markupMax: 15 },
    );
    expect(pool.map((p) => p.promotion_id)).toEqual(['S-ok']);
  });

  it('ignores non-writable types', () => {
    const pool = selectParaGanarPromoPool(
      [{ promotion_id: 'X', promotion_type: 'DOD', status: 'candidate', name: 'DOD' }],
      { precioSugerido: 10 },
    );
    expect(pool).toEqual([]);
  });
});
