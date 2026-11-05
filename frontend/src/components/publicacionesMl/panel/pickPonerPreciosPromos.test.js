import { describe, it, expect } from 'vitest';
import {
  baselineMarkupFromPromos,
  bestByMarkup,
  enrollBodyForPromo,
  esMejorOferta,
  hasPickedSlot,
  listRowForPricelist,
  pickMejoresCandidatas,
  pickPonerPreciosPromos,
  pricesClose,
} from './pickPonerPreciosPromos';
import { LISTS } from '../../pricing/priceWrites';
import capture from './fixtures/ponerPreciosPromos.capture.json';

function asApiPromo(raw, nuestro_markup) {
  return {
    promotion_id: raw.id,
    promotion_type: raw.type,
    status: raw.status,
    name: raw.name,
    price: raw.price,
    original_price: raw.original_price,
    suggested_discounted_price: raw.suggested_discounted_price,
    min_discounted_price: raw.min_discounted_price,
    max_discounted_price: raw.max_discounted_price,
    meli_percentage: raw.meli_percentage,
    seller_percentage: raw.seller_percentage,
    nuestro_markup,
  };
}

const markups = { SMART: 22, DEAL: 8, SELLER_CAMPAIGN: 12 };
const captured = capture.promotions.map((raw) => asApiPromo(raw, markups[raw.type]));

describe('pickPonerPreciosPromos', () => {
  it('picks best SMART/DEAL and Premium of the month from a capture', () => {
    const picked = pickPonerPreciosPromos(captured, { monthName: 'octubre' });
    expect(picked.smart.promotion_id).toBe('P-MLA18137008');
    expect(picked.deal.promotion_id).toBe('P-MLA18067012');
    expect(picked.premium.promotion_id).toBe('C-MLA1669550');
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

  it('builds SMART and DEAL enroll bodies from captured fields', () => {
    const smart = captured.find((p) => p.promotion_type === 'SMART');
    const deal = captured.find((p) => p.promotion_type === 'DEAL');
    expect(enrollBodyForPromo(smart)).toEqual({
      promotion_id: 'P-MLA18137008',
      promotion_type: 'SMART',
      precio_visto: 74690,
      markup_visto: 22,
    });
    expect(enrollBodyForPromo(deal)).toMatchObject({
      promotion_id: 'P-MLA18067012',
      promotion_type: 'DEAL',
      deal_price: 77000,
    });
  });

  it('maps pricelist ids to Lista ML rows', () => {
    expect(listRowForPricelist(4, LISTS)?.id).toBe('ml-clasica');
    expect(listRowForPricelist(17, LISTS)?.id).toBe('ml-3');
  });
});

describe('baselineMarkupFromPromos', () => {
  it('uses max cofunded started markup when offer price matches sale (same as backend)', () => {
    expect(
      baselineMarkupFromPromos(
        [
          {
            status: 'started',
            promotion_type: 'PRICE_MATCHING',
            application_status: 'programmed',
            price: 555867.8,
            nuestro_markup: 1.2,
          },
          {
            status: 'started',
            promotion_type: 'SMART',
            application_status: 'active',
            price: 555867.5,
            nuestro_markup: 1.4,
          },
          {
            status: 'candidate',
            promotion_type: 'SMART',
            price: 526957,
            nuestro_markup: -5.06,
          },
        ],
        555867.83,
      ),
    ).toBe(1.4);
  });

  it('returns null without a matching cofunded started offer', () => {
    expect(
      baselineMarkupFromPromos(
        [{ status: 'candidate', promotion_type: 'SMART', price: 526957, nuestro_markup: -5.06 }],
        555867.83,
      ),
    ).toBeNull();
    expect(pricesClose(555867.83, 555867.8)).toBe(true);
    expect(pricesClose(555867.83, 400000)).toBe(false);
  });
});

describe('esMejorOferta / pickMejoresCandidatas', () => {
  it('rejects markup↑ at a higher consumer price', () => {
    expect(esMejorOferta(1100, 30, 1000, 20)).toBe(false);
    expect(esMejorOferta(1000, 30, 1000, 20)).toBe(true);
    expect(esMejorOferta(1000, 20, 1000, 20)).toBe(false);
    expect(esMejorOferta(900, 20, 1000, 20)).toBe(true);
    expect(esMejorOferta(900, 25, 1000, 20)).toBe(true);
  });

  it('keeps only slots that beat the status quo, best SMART when two qualify', () => {
    const promotions = [
      asApiPromo(capture.promotions[0], 22),
      {
        ...asApiPromo(capture.promotions[0], 18),
        promotion_id: 'P-WEAKER-SMART',
        price: 74000,
      },
      asApiPromo(capture.promotions[1], 8),
      asApiPromo(capture.promotions[2], 12),
    ];
    // Baseline above SMART offer price with lower markup → SMART qualifies; DEAL 8% does not beat 20%.
    const picked = pickMejoresCandidatas(promotions, {
      baselinePrice: 80000,
      baselineMarkup: 20,
      monthName: 'octubre',
    });
    expect(picked.smart.promotion_id).toBe('P-MLA18137008');
    expect(picked.deal).toBeNull();
    expect(picked.premium).toBeNull();
    expect(hasPickedSlot(picked)).toBe(true);
  });
});
