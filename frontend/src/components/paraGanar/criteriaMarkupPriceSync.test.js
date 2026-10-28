import { describe, expect, it } from 'vitest';
import {
  markupFromPrice,
  priceFromMarkup,
  syncLinkedCriteriaField,
} from './criteriaMarkupPriceSync';

describe('criteriaMarkupPriceSync', () => {
  it('converts markup to price and back on ERP cost ARS', () => {
    expect(priceFromMarkup(100, 10)).toBe(110);
    expect(markupFromPrice(100, 110)).toBe(10);
  });

  it('syncs peer fields when editing markup or price', () => {
    const base = {
      markup_min: '5',
      precio_min: '',
      markup_max: '15',
      precio_max: '',
    };
    expect(syncLinkedCriteriaField(base, 'markup_min', '10', 200).precio_min).toBe('220');
    expect(syncLinkedCriteriaField(base, 'precio_max', '230', 200).markup_max).toBe('15');
  });

  it('skips sync without a positive cost', () => {
    const base = { markup_min: '5', precio_min: '1' };
    expect(syncLinkedCriteriaField(base, 'markup_min', '10', null).precio_min).toBe('1');
  });
});
