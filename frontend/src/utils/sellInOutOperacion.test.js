import { describe, expect, it } from 'vitest';
import * as sellInOutOperacion from './sellInOutOperacion';

const { lineaSellOut, partesSellInOut } = sellInOutOperacion;
const moneda = (monto) => `$ ${Number(monto).toFixed(0)}`;

describe('partesSellInOut', () => {
  it('names the sell out and marks it while its rate is an estimate', () => {
    expect(partesSellInOut({ sell_out_ars: 50, sell_out_estimado: false }, moneda)).toEqual(['Sell out: $ 50']);
    expect(partesSellInOut({ sell_out_ars: 50, sell_out_estimado: true }, moneda)).toEqual([
      'Sell out: $ 50 (estimado: tipo de cambio a definir)',
    ]);
  });

  it('says a USD sell out has no rate yet, and names nothing without one', () => {
    expect(partesSellInOut({ sell_out_ars: null, sell_out_estimado: true }, moneda)).toEqual([
      'Sell out en USD sin tipo de cambio',
    ]);
    expect(partesSellInOut({ sell_out_ars: null, sell_out_estimado: false }, moneda)).toEqual([]);
  });
});

describe('lineaSellOut', () => {
  it('reads out, out ≈ while estimated, a definir while unknown and null without one', () => {
    expect(lineaSellOut({ sell_out_ars: 50 }, moneda)).toBe('out $ 50');
    expect(lineaSellOut({ sell_out_ars: 50, sell_out_estimado: true }, moneda)).toBe('out ≈ $ 50');
    expect(lineaSellOut({ sell_out_ars: null, sell_out_estimado: true }, moneda)).toBe('out a definir');
    expect(lineaSellOut({ sell_out_ars: null }, moneda)).toBeNull();
  });
});

describe('Ventas fuera de ML operations (costo SI T5 PR B)', () => {
  it('has no "c/ sell in" cells any more: their fields were always null and are gone', () => {
    expect(sellInOutOperacion.celdasSellInOut).toBeUndefined();
  });
});
