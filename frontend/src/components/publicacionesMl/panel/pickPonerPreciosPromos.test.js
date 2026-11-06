import { describe, it, expect } from 'vitest';
import {
  baselineMarkupFromPromos,
  baselineSellInOutFromPromos,
  bestByMarkup,
  enrollBodyForPromo,
  esMejorOferta,
  hasPickedSlot,
  listRowForPricelist,
  pickMejoresCandidatas,
  pickPonerPreciosPromos,
  pricesClose,
  rankingMarkupOf,
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
    // A DEAL is applied at its max (the smallest discount ML accepts), the same price the row shows.
    expect(enrollBodyForPromo(deal)).toMatchObject({
      promotion_id: 'P-MLA18067012',
      promotion_type: 'DEAL',
      deal_price: 84467.35,
    });
  });

  it('clamps the enroll price with each bound ML sends, like the row display', () => {
    expect(
      enrollBodyForPromo({ promotion_id: 'P-D', promotion_type: 'DEAL', price: 100, max_discounted_price: 90 }),
    ).toEqual({ promotion_id: 'P-D', promotion_type: 'DEAL', deal_price: 90 });
    expect(
      enrollBodyForPromo({
        promotion_id: 'P-S',
        promotion_type: 'SELLER_CAMPAIGN',
        suggested_discounted_price: 50,
        min_discounted_price: 60,
      }),
    ).toEqual({ promotion_id: 'P-S', promotion_type: 'SELLER_CAMPAIGN', deal_price: 60 });
    expect(
      enrollBodyForPromo({
        promotion_id: 'P-S',
        promotion_type: 'SELLER_CAMPAIGN',
        suggested_discounted_price: 70,
        min_discounted_price: 60,
        max_discounted_price: 65,
      }),
    ).toEqual({ promotion_id: 'P-S', promotion_type: 'SELLER_CAMPAIGN', deal_price: 65 });
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

// promos-markup-sell-in-out S2: the "Markup vigente" line's extra figure comes from the same offer.
describe('baselineSellInOutFromPromos', () => {
  const started = (price, markup, sellInOut) => ({
    status: 'started',
    promotion_type: 'SMART',
    price,
    nuestro_markup: markup,
    markup_sell_in_out: sellInOut,
  });

  it('takes the sell in / sell out markup of the offer the vigente markup comes from', () => {
    expect(
      baselineSellInOutFromPromos([started(555867.8, 1.2, 9.9), started(555867.5, 1.4, 3.1)], 555867.83),
    ).toBe(3.1);
  });

  it('is null when that offer has none, or there is no matching offer', () => {
    expect(baselineSellInOutFromPromos([started(555867.8, 1.4, null)], 555867.83)).toBeNull();
    expect(baselineSellInOutFromPromos([started(400000, 1.4, 3.1)], 555867.83)).toBeNull();
  });
});

describe('ranking with sell in / sell out (S5)', () => {
  const candidate = (id, type, price, nuestro, sellInOut) => ({
    promotion_id: id,
    promotion_type: type,
    status: 'candidate',
    price,
    nuestro_markup: nuestro,
    markup_sell_in_out: sellInOut,
  });

  it('ranks by markup_sell_in_out when there is one, else by nuestro_markup', () => {
    expect(rankingMarkupOf({ nuestro_markup: 20, markup_sell_in_out: 31 })).toBe(31);
    expect(rankingMarkupOf({ nuestro_markup: 20, markup_sell_in_out: null })).toBe(20);
    expect(rankingMarkupOf({ nuestro_markup: null, markup_sell_in_out: 31 })).toBeNull();
    expect(rankingMarkupOf({})).toBeNull();
  });

  it('picks B over A when the plain markup favours A but sell in / sell out favours B', () => {
    const a = candidate('A', 'SMART', 900, 25, 26);
    const b = candidate('B', 'SMART', 900, 20, 30);
    expect(bestByMarkup([a, b])).toBe(b);
    expect(pickPonerPreciosPromos([a, b]).smart).toBe(b);
  });

  it('compares a candidate without sell in / sell out by its plain markup', () => {
    const a = candidate('A', 'SMART', 900, 28, null);
    const b = candidate('B', 'SMART', 900, 20, 27);
    expect(bestByMarkup([a, b])).toBe(a);
  });

  it('beats the status quo only by the markups with sell in / sell out on both sides', () => {
    // Plain: 22 > 21 would beat it; with sell in / sell out: 24 < 25 does not.
    const promo = candidate('A', 'SMART', 1000, 22, 24);
    expect(pickMejoresCandidatas([promo], { baselinePrice: 1000, baselineMarkup: 25 }).smart).toBeNull();
    // Plain: 18 < 21 would not; with sell in / sell out: 26 > 25 does.
    const other = candidate('B', 'SMART', 1000, 18, 26);
    expect(pickMejoresCandidatas([other], { baselinePrice: 1000, baselineMarkup: 25 }).smart).toBe(other);
  });

  it('uses the candidate plain markup against the baseline when the candidate has no sell in / sell out', () => {
    const promo = candidate('A', 'SMART', 1000, 26, null);
    expect(pickMejoresCandidatas([promo], { baselinePrice: 1000, baselineMarkup: 25 }).smart).toBe(promo);
  });
});
