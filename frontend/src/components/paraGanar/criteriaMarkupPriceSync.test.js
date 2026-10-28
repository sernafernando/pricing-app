import { describe, expect, it, vi } from 'vitest';
import { MARKUP_PRICE_LINKS, resolveLinkedCriteriaValue } from './criteriaMarkupPriceSync';

describe('criteriaMarkupPriceSync (Pricing endpoints)', () => {
  it('maps markup ↔ precio peers', () => {
    expect(MARKUP_PRICE_LINKS.markup_min).toBe('precio_min');
    expect(MARKUP_PRICE_LINKS.precio_max).toBe('markup_max');
  });

  it('clears peer when the edited value is empty', async () => {
    const result = await resolveLinkedCriteriaValue({
      key: 'markup_min',
      rawValue: '  ',
      itemId: 1,
      pricelistId: 4,
      calcularPorMarkup: vi.fn(),
      calcularMarkup: vi.fn(),
    });
    expect(result).toEqual({ peer: 'precio_min', peerValue: '' });
  });

  it('uses calcular-por-markup for markup edits (adicional 0)', async () => {
    const calcularPorMarkup = vi.fn().mockResolvedValue({ data: { precio: 12345.678 } });
    const result = await resolveLinkedCriteriaValue({
      key: 'markup_min',
      rawValue: '10',
      itemId: 42,
      pricelistId: 4,
      calcularPorMarkup,
      calcularMarkup: vi.fn(),
    });
    expect(calcularPorMarkup).toHaveBeenCalledWith({
      item_id: 42,
      pricelist_id: 4,
      markup_objetivo: 10,
      adicional_markup: 0,
    });
    expect(result).toEqual({ peer: 'precio_min', peerValue: '12345.68' });
  });

  it('uses calcular-markup for price edits', async () => {
    const calcularMarkup = vi.fn().mockResolvedValue({ data: { markup: 8.5 } });
    const result = await resolveLinkedCriteriaValue({
      key: 'precio_max',
      rawValue: '20000',
      itemId: 42,
      pricelistId: 17,
      calcularPorMarkup: vi.fn(),
      calcularMarkup,
    });
    expect(calcularMarkup).toHaveBeenCalledWith({
      item_id: 42,
      pricelist_id: 17,
      precio: 20000,
    });
    expect(result).toEqual({ peer: 'markup_max', peerValue: '8.5' });
  });
});
