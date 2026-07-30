import { describe, it, expect } from 'vitest';
import { derivePromosByType } from './derivePromosByType';

function cacheRefFrom(entries) {
  return { current: new Map(entries) };
}

describe('derivePromosByType', () => {
  it('returns an empty object when the cache is empty', () => {
    expect(derivePromosByType(cacheRefFrom([]))).toEqual({});
  });

  it('returns an empty object when the ref/current is missing', () => {
    expect(derivePromosByType(undefined)).toEqual({});
    expect(derivePromosByType({})).toEqual({});
  });

  it('groups distinct names by promotion_type across a single MLA entry', () => {
    const cacheRef = cacheRefFrom([
      [
        'MLA1',
        {
          status: 'ok',
          data: {
            promotions: [
              { promotion_type: 'DEAL', name: '2x1' },
              { promotion_type: 'DEAL', name: '3x2' },
              { promotion_type: 'SMART', name: 'Promo Smart' },
            ],
          },
        },
      ],
    ]);

    expect(derivePromosByType(cacheRef)).toEqual({
      DEAL: ['2x1', '3x2'],
      SMART: ['Promo Smart'],
    });
  });

  it('merges and dedupes names across multiple MLA entries', () => {
    const cacheRef = cacheRefFrom([
      ['MLA1', { status: 'ok', data: { promotions: [{ promotion_type: 'DEAL', name: '2x1' }] } }],
      [
        'MLA2',
        {
          status: 'ok',
          data: { promotions: [{ promotion_type: 'DEAL', name: '2x1' }, { promotion_type: 'DEAL', name: '3x2' }] },
        },
      ],
    ]);

    expect(derivePromosByType(cacheRef)).toEqual({ DEAL: ['2x1', '3x2'] });
  });

  it('ignores entries with status "error" (nothing fetched successfully)', () => {
    const cacheRef = cacheRefFrom([['MLA1', { status: 'error', error: new Error('boom') }]]);
    expect(derivePromosByType(cacheRef)).toEqual({});
  });

  it('normalizes a missing/empty name to null and groups it as (sin nombre)', () => {
    const cacheRef = cacheRefFrom([
      ['MLA1', { status: 'ok', data: { promotions: [{ promotion_type: 'DOD', name: null }] } }],
    ]);
    expect(derivePromosByType(cacheRef)).toEqual({ DOD: [null] });
  });
});
