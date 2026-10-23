import { describe, expect, it } from 'vitest';
import { celdasSellInOut } from './sellInOutOperacion';

const moneda = (monto) => `$ ${Number(monto).toFixed(0)}`;
const porcentaje = (valor) => `${(Number(valor) * 100).toFixed(2)}%`;
const celdas = (op) => celdasSellInOut(op, { moneda, porcentaje });

const SIN_CONSUMOS = {
  sell_in_ars: null,
  sell_out_ars: null,
  sell_out_estimado: null,
  costo_con_sell_in: null,
  ganancia_con_sell_in_out: null,
  markup_con_sell_in_out: null,
};

describe('celdasSellInOut', () => {
  it('shows a dash in both cells for an operation without sell in or sell out', () => {
    expect(celdas({ ...SIN_CONSUMOS })).toEqual({
      costo: { texto: '-', title: undefined },
      markup: { texto: '-', title: undefined, negativo: false },
    });
  });

  it('treats an older response without the fields like one without consumos', () => {
    expect(celdas({}).costo.texto).toBe('-');
    expect(celdas({}).markup.texto).toBe('-');
  });

  it('shows the cost with sell in and the markup with both, naming the amounts in the tooltip', () => {
    const result = celdas({
      ...SIN_CONSUMOS,
      sell_in_ars: 100,
      sell_out_ars: 50,
      sell_out_estimado: false,
      costo_con_sell_in: 900,
      ganancia_con_sell_in_out: 450,
      markup_con_sell_in_out: 0.5,
    });

    expect(result.costo).toEqual({ texto: '$ 900', title: 'Sell in: $ 100' });
    expect(result.markup).toEqual({ texto: '50.00%', title: 'Sell in: $ 100 · Sell out: $ 50', negativo: false });
  });

  it('names only the kind the operation has', () => {
    const result = celdas({ ...SIN_CONSUMOS, sell_out_ars: 50, sell_out_estimado: false, costo_con_sell_in: 1000, markup_con_sell_in_out: 0.1 });

    expect(result.costo.title).toBeUndefined();
    expect(result.markup.title).toBe('Sell out: $ 50');
  });

  it('marks an estimated sell out and keeps its markup', () => {
    const result = celdas({ ...SIN_CONSUMOS, sell_out_ars: 50, sell_out_estimado: true, costo_con_sell_in: 1000, markup_con_sell_in_out: 0.1 });

    expect(result.markup.texto).toBe('≈ 10.00%');
    expect(result.markup.title).toBe('Sell out: $ 50 (estimado: tipo de cambio a definir)');
  });

  it('says the markup is pending while the sell out amount is unknown', () => {
    const result = celdas({ ...SIN_CONSUMOS, sell_in_ars: 100, sell_out_estimado: true, costo_con_sell_in: 900 });

    expect(result.costo.texto).toBe('$ 900');
    expect(result.markup).toEqual({
      texto: 'A definir',
      title: 'Sell in: $ 100 · Sell out en USD sin tipo de cambio',
      negativo: false,
    });
  });

  it('flags a negative markup', () => {
    const result = celdas({ ...SIN_CONSUMOS, sell_in_ars: 10, costo_con_sell_in: 990, markup_con_sell_in_out: -0.2 });

    expect(result.markup.negativo).toBe(true);
  });
});
