import { describe, it, expect } from 'vitest';
import { mlSaleUrl, paymentMethodLabel, formatDay, timeAgo } from './ventasMlFormat';

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

describe('timeAgo', () => {
  const now = new Date('2026-09-30T12:00:00Z');
  const ago = (ms) => new Date(now.getTime() - ms).toISOString();

  it('says just now under a minute', () => {
    expect(timeAgo(ago(20_000), now)).toBe('hace instantes');
  });

  it('counts minutes, hours and days', () => {
    expect(timeAgo(ago(3 * 60_000), now)).toBe('hace 3 min');
    expect(timeAgo(ago(2 * 3_600_000), now)).toBe('hace 2 h');
    expect(timeAgo(ago(3 * 86_400_000), now)).toBe('hace 3 d');
  });

  it('never shows a negative age for a clock a bit ahead of ours', () => {
    expect(timeAgo(ago(-5_000), now)).toBe('hace instantes');
  });

  it('is null when there is no timestamp, so nothing is claimed', () => {
    expect(timeAgo(null, now)).toBeNull();
    expect(timeAgo('garbage', now)).toBeNull();
  });
});
