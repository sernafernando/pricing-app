import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { describe, it, expect } from 'vitest';
import {
  baselineMarkupFromPromos,
  baselineSellInOutFromPromos,
  bestByMarkup,
  enrollBodyForPromo,
  esMejorOferta,
  hasPickedSlot,
  isApplicableNow,
  listRowForPricelist,
  pickMejoresCandidatas,
  parsePromoInstant,
  pickPonerPreciosPromos,
  pricesClose,
  comparableMarkups,
  slotEntries,
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
    expect(picked.SMART.promotion_id).toBe('P-MLA18137008');
    expect(picked.DEAL.promotion_id).toBe('P-MLA18067012');
    expect(picked.SELLER_CAMPAIGN.promotion_id).toBe('C-MLA1669550');
    expect(picked.PRICE_MATCHING).toBeNull();
    expect(picked.PRE_NEGOTIATED).toBeNull();
    expect(picked.LIGHTNING).toBeNull();
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

  it('builds LIGHTNING enroll body with deal_price and stock.min', () => {
    expect(
      enrollBodyForPromo({
        promotion_id: 'L-1',
        promotion_type: 'LIGHTNING',
        status: 'candidate',
        suggested_discounted_price: 12000,
        price: 15000,
        nuestro_markup: 5,
        payload: { stock: { min: 3, max: 10 } },
      }),
    ).toEqual({
      promotion_id: 'L-1',
      promotion_type: 'LIGHTNING',
      deal_price: 12000,
      stock: 3,
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
    expect(picked.SMART.promotion_id).toBe('P-MLA18137008');
    expect(picked.DEAL).toBeNull();
    expect(picked.SELLER_CAMPAIGN).toBeNull();
    expect(hasPickedSlot(picked)).toBe(true);
  });

  it('surfaces a PRICE_MATCHING-only better candidate', () => {
    const picked = pickMejoresCandidatas(
      [
        {
          status: 'candidate',
          promotion_type: 'PRICE_MATCHING',
          promotion_id: 'PM-1',
          price: 90000,
          nuestro_markup: 15,
          name: 'Gánale a la competencia',
        },
      ],
      { baselinePrice: 100000, baselineMarkup: 10, monthName: 'noviembre' },
    );
    expect(picked.PRICE_MATCHING.promotion_id).toBe('PM-1');
    expect(picked.SMART).toBeNull();
    expect(picked.DEAL).toBeNull();
    expect(slotEntries(picked).map(([type]) => type)).toEqual(['PRICE_MATCHING']);
  });

  it('fills independent MeLi-type slots without competing across types', () => {
    const picked = pickMejoresCandidatas(
      [
        {
          status: 'candidate',
          promotion_type: 'SMART',
          promotion_id: 'S-1',
          price: 90000,
          nuestro_markup: 12,
        },
        {
          status: 'candidate',
          promotion_type: 'PRE_NEGOTIATED',
          promotion_id: 'PN-1',
          price: 88000,
          nuestro_markup: 14,
        },
        {
          status: 'candidate',
          promotion_type: 'PRICE_MATCHING',
          promotion_id: 'PM-1',
          price: 87000,
          nuestro_markup: 11,
        },
        {
          status: 'candidate',
          promotion_type: 'LIGHTNING',
          promotion_id: 'L-1',
          price: 85000,
          suggested_discounted_price: 85000,
          nuestro_markup: 13,
          payload: { stock: { min: 2, max: 8 } },
        },
        {
          status: 'candidate',
          promotion_type: 'LIGHTNING',
          promotion_id: 'L-NO-STOCK',
          price: 84000,
          suggested_discounted_price: 84000,
          nuestro_markup: 20,
        },
      ],
      { baselinePrice: 100000, baselineMarkup: 10, monthName: 'noviembre' },
    );
    expect(picked.SMART.promotion_id).toBe('S-1');
    expect(picked.PRE_NEGOTIATED.promotion_id).toBe('PN-1');
    expect(picked.PRICE_MATCHING.promotion_id).toBe('PM-1');
    expect(picked.LIGHTNING.promotion_id).toBe('L-1');
    expect(slotEntries(picked).map(([type]) => type)).toEqual([
      'SMART',
      'PRE_NEGOTIATED',
      'PRICE_MATCHING',
      'LIGHTNING',
    ]);
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

  it('compares with sell in / sell out only when both sides have it, else both plain', () => {
    expect(comparableMarkups({ nuestro_markup: 20, markup_sell_in_out: 31 }, { nuestro_markup: 18, markup_sell_in_out: 29 })).toEqual([31, 29]);
    expect(comparableMarkups({ nuestro_markup: 20, markup_sell_in_out: null }, { nuestro_markup: 18, markup_sell_in_out: 29 })).toEqual([20, 18]);
    expect(comparableMarkups({ nuestro_markup: 20, markup_sell_in_out: 31 }, { nuestro_markup: 18, markup_sell_in_out: null })).toEqual([20, 18]);
    expect(comparableMarkups({ nuestro_markup: null, markup_sell_in_out: 31 }, { nuestro_markup: 18, markup_sell_in_out: 29 })).toEqual([null, 18]);
  });

  it('picks B over A when the plain markup favours A but sell in / sell out favours B', () => {
    const a = candidate('A', 'SMART', 900, 25, 26);
    const b = candidate('B', 'SMART', 900, 20, 30);
    expect(bestByMarkup([a, b])).toBe(b);
    expect(pickPonerPreciosPromos([a, b]).SMART).toBe(b);
  });

  it('ranks every MeLi-type slot with the same sell in / sell out rule, not only SMART', () => {
    const a = candidate('A', 'PRE_NEGOTIATED', 900, 25, 26);
    const b = candidate('B', 'PRE_NEGOTIATED', 900, 20, 30);
    const c = candidate('C', 'PRICE_MATCHING', 900, 25, 26);
    const d = candidate('D', 'PRICE_MATCHING', 900, 20, 30);
    const picked = pickPonerPreciosPromos([a, b, c, d]);
    expect(picked.PRE_NEGOTIATED).toBe(b);
    expect(picked.PRICE_MATCHING).toBe(d);
    const baseline = { baselinePrice: 1000, baselineMarkup: 21, baselineSellInOut: 25 };
    // Plain 22 >= 21 would beat it; with sell in / sell out 24 < 25 does not.
    expect(pickMejoresCandidatas([candidate('E', 'PRE_NEGOTIATED', 1000, 22, 24)], baseline).PRE_NEGOTIATED).toBeNull();
  });

  it('ranks a mixed set plain: one candidate without sell in / sell out puts them all on the plain markup', () => {
    const a = candidate('A', 'SMART', 900, 22, null);
    const b = candidate('B', 'SMART', 900, 20, 30);
    expect(bestByMarkup([a, b])).toBe(a);
  });

  it('beats the status quo with sell in / sell out when both sides have it', () => {
    const baseline = { baselinePrice: 1000, baselineMarkup: 21, baselineSellInOut: 25 };
    // Plain 22 >= 21 would beat it; with sell in / sell out 24 < 25 does not.
    expect(pickMejoresCandidatas([candidate('A', 'SMART', 1000, 22, 24)], baseline).SMART).toBeNull();
    const other = candidate('B', 'SMART', 1000, 18, 26);
    expect(pickMejoresCandidatas([other], baseline).SMART).toBe(other);
  });

  it('compares plain on both sides when the candidate or the status quo has no sell in / sell out', () => {
    const conSellInOut = { baselinePrice: 1000, baselineMarkup: 21, baselineSellInOut: 25 };
    // The candidate's could not be computed: 22 against the plain 21, never against 25.
    const sinCandidata = candidate('A', 'SMART', 1000, 22, null);
    expect(pickMejoresCandidatas([sinCandidata], conSellInOut).SMART).toBe(sinCandidata);
    // The status quo has none: B's 30 is never compared against a plain 21.
    const b = candidate('B', 'SMART', 1000, 20, 30);
    expect(pickMejoresCandidatas([b], { baselinePrice: 1000, baselineMarkup: 21, baselineSellInOut: null }).SMART).toBeNull();
  });
});

/**
 * The applicable-now rule (pubml-promo-mejor S2) on the SAME cases the backend runs: read from the backend's fixture
 * (vitest runs from `frontend/`), so a case added there runs here too.
 */
const applicableCases = JSON.parse(
  readFileSync(resolve(cwd(), '../backend/tests/fixtures/candidata_aplicable_cases.json'), 'utf8'),
);

describe('isApplicableNow (shared with backend candidata_aplicable_ahora)', () => {
  const now = new Date(applicableCases.now);
  it.each(applicableCases.cases)('$name', ({ entry, applicable }) => {
    const { type, ...rest } = entry;
    const promo = { status: 'candidate', promotion_type: type, ...rest };
    expect(isApplicableNow(promo, { now, monthName: 'noviembre' })).toBe(applicable);
  });

  it('reads naive dates as UTC, not as local time', () => {
    expect(parsePromoInstant('2026-11-13T10:00:00')).toBe(Date.UTC(2026, 10, 13, 10));
    expect(parsePromoInstant('2026-11-13', { endOfDay: true })).toBe(Date.UTC(2026, 10, 14));
    expect(parsePromoInstant('soon')).toBeNull();
  });
});

describe('pickMejoresCandidatas drops candidates not applicable now', () => {
  const now = new Date('2026-11-13T15:00:00Z');
  const base = { baselinePrice: 100000, baselineMarkup: 10, now, monthName: 'noviembre' };
  const smart = (id, extra) => ({ status: 'candidate', promotion_type: 'SMART', promotion_id: id, price: 90000, nuestro_markup: 15, ...extra });

  it('drops a candidate that starts in 10 days', () => {
    expect(pickMejoresCandidatas([smart('FUT', { start_date: '2026-11-23T00:00:00' })], base).SMART).toBeNull();
  });

  it('drops an expired candidate', () => {
    expect(pickMejoresCandidatas([smart('EXP', { finish_date: '2026-11-12T23:59:59' })], base).SMART).toBeNull();
  });

  it('keeps the applicable one when a better future one exists', () => {
    const later = smart('FUT', { start_date: '2026-11-23T00:00:00', nuestro_markup: 30 });
    const today = smart('NOW', { start_date: '2026-11-01T00:00:00', finish_date: '2026-11-30T23:59:59' });
    expect(pickMejoresCandidatas([later, today], base).SMART.promotion_id).toBe('NOW');
  });
});
