import { describe, it, expect } from 'vitest';
import { mlSaleUrl, paymentMethodLabel, formatDay } from './ventasMlFormat';

describe('mlSaleUrl', () => {
  it('points at the seller sale detail by order id', () => {
    expect(mlSaleUrl({ orderId: 2000018567320906, packId: null })).toBe(
      'https://www.mercadolibre.com.ar/ventas/2000018567320906/detalle',
    );
  });

  it('uses the pack id when the order belongs to a pack', () => {
    expect(mlSaleUrl({ orderId: 1, packId: 2000099900000001 })).toBe(
      'https://www.mercadolibre.com.ar/ventas/2000099900000001/detalle',
    );
  });

  it('returns null without an id (the link is hidden, never broken)', () => {
    expect(mlSaleUrl({ orderId: null, packId: null })).toBeNull();
  });
});

describe('paymentMethodLabel', () => {
  it('names the common ML methods', () => {
    expect(paymentMethodLabel('account_money')).toBe('Dinero en cuenta');
    expect(paymentMethodLabel('master')).toBe('Mastercard');
    expect(paymentMethodLabel('visa')).toBe('Visa');
  });

  it('falls back to the raw id for a method we do not know, never hides it', () => {
    expect(paymentMethodLabel('some_new_method')).toBe('some_new_method');
  });

  it('is null when there is no payment method', () => {
    expect(paymentMethodLabel(null)).toBeNull();
  });
});

describe('formatDay', () => {
  it('formats an ISO timestamp as a day only', () => {
    expect(formatDay('2026-09-12T12:00:00.000Z')).toBe('12/09/2026');
  });

  it('is an em dash for an absent or invalid value', () => {
    expect(formatDay(null)).toBe('—');
    expect(formatDay('not a date')).toBe('—');
  });
});
