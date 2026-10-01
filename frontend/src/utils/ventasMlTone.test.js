import { describe, it, expect } from 'vitest';
import {
  markupTone,
  formatMarkup,
  moneyTone,
  formatSignedMoney,
  formatListMoney,
  formatDeduction,
  shippingStatusLabel,
  OPERATION_STATUS_TONE,
  GOODS_STATUS_TONE,
} from './ventasMlTone';

describe('markupTone', () => {
  // Same cut points the rentabilidad dashboards already use
  // (`TabRentabilidad.jsx` getMarkupColor: <0 red, <3 orange, <6 yellow,
  // else green), with orange+yellow collapsed into one "low" amber.
  it('is negative below zero', () => {
    expect(markupTone(-0.1)).toBe('negative');
    expect(markupTone(-8.4)).toBe('negative');
  });

  it('is low from zero up to (not including) 6%', () => {
    expect(markupTone(0)).toBe('low');
    expect(markupTone(5.99)).toBe('low');
  });

  it('is good from 6% up', () => {
    expect(markupTone(6)).toBe('good');
    expect(markupTone(21.6)).toBe('good');
  });

  it('has no tone when the markup is unknown -- never painted as a zero', () => {
    expect(markupTone(null)).toBeNull();
    expect(markupTone(undefined)).toBeNull();
    expect(markupTone('not a number')).toBeNull();
  });
});

describe('formatMarkup', () => {
  it('signs a positive markup with +, like the design', () => {
    expect(formatMarkup(21.6)).toBe('+21,6%');
  });

  it('keeps the minus on a negative markup', () => {
    expect(formatMarkup(-8.4)).toBe('-8,4%');
  });

  it('renders zero without a sign', () => {
    expect(formatMarkup(0)).toBe('0%');
  });

  it('renders an unknown markup as a dash', () => {
    expect(formatMarkup(null)).toBe('—');
  });
});

describe('moneyTone', () => {
  it('classifies the sign of an amount', () => {
    expect(moneyTone(-1)).toBe('negative');
    expect(moneyTone(1)).toBe('positive');
    expect(moneyTone(0)).toBe('zero');
    expect(moneyTone(null)).toBeNull();
  });
});

describe('formatSignedMoney', () => {
  it('puts the minus before the currency sign on a negative amount', () => {
    expect(formatSignedMoney(-74676.08)).toBe('-$ 74.676,08');
  });

  it('renders a positive amount with the currency sign', () => {
    expect(formatSignedMoney(597408.67)).toBe('$ 597.408,67');
  });

  it('renders an unknown amount as a dash, never $ 0', () => {
    expect(formatSignedMoney(null)).toBe('—');
    expect(formatSignedMoney(undefined)).toBe('—');
  });
});

describe('formatListMoney', () => {
  it('prefixes pesos with $ and puts the minus first', () => {
    expect(formatListMoney(1234567.89, 'ARS')).toBe('$ 1.234.567,89');
    expect(formatListMoney(-32450.8, 'ARS')).toBe('-$ 32.450,80');
  });

  it('treats a missing currency as the listing default (pesos)', () => {
    expect(formatListMoney(10, null)).toBe('$ 10,00');
  });

  it('spells a foreign currency out instead of passing it off as pesos', () => {
    expect(formatListMoney(82.5, 'USD')).toBe('82,50 USD');
    expect(formatListMoney(-82.5, 'USD')).toBe('-82,50 USD');
  });

  it('renders an unknown amount as a dash', () => {
    expect(formatListMoney(null, 'ARS')).toBe('—');
  });
});

describe('formatDeduction', () => {
  // A breakdown line's `monto` is a CHARGE (positive = it came off the sale).
  it('renders a charge as a red (−) subtraction', () => {
    expect(formatDeduction(74676.08)).toEqual({ sign: '(−)', text: '-$ 74.676,08', tone: 'negative' });
  });

  it('renders a net refund (negative charge) as a green (+) addition', () => {
    expect(formatDeduction(-1200)).toEqual({ sign: '(+)', text: '$ 1.200,00', tone: 'positive' });
  });

  it('renders an unknown charge as a neutral dash', () => {
    expect(formatDeduction(null)).toEqual({ sign: '(−)', text: '—', tone: null });
  });
});

describe('shippingStatusLabel', () => {
  it('translates a known substatus first', () => {
    expect(shippingStatusLabel({ status: 'shipped', substatus: 'out_for_delivery' })).toBe('En reparto');
  });

  it('falls back to the translated status when the substatus is unknown or absent', () => {
    expect(shippingStatusLabel({ status: 'shipped', substatus: 'something_new' })).toBe('En camino');
    expect(shippingStatusLabel({ status: 'delivered', substatus: null })).toBe('Entregado');
  });

  it('shows a value it cannot translate verbatim instead of hiding it', () => {
    expect(shippingStatusLabel({ status: 'brand_new_status', substatus: null })).toBe('brand_new_status');
  });

  it('returns null when there is nothing to show', () => {
    expect(shippingStatusLabel({ status: null, substatus: null })).toBeNull();
    expect(shippingStatusLabel(null)).toBeNull();
  });
});

describe('status tones', () => {
  it('paints Pagada green and Cancelada red, like the design', () => {
    expect(OPERATION_STATUS_TONE.paid).toBe('success');
    expect(OPERATION_STATUS_TONE.cancelled).toBe('danger');
    expect(OPERATION_STATUS_TONE.in_dispute).toBe('warning');
  });

  it('paints goods in transit blue and delivered green', () => {
    expect(GOODS_STATUS_TONE.in_transit).toBe('info');
    expect(GOODS_STATUS_TONE.delivered).toBe('success');
    expect(GOODS_STATUS_TONE.returned_undelivered).toBe('danger');
  });
});
