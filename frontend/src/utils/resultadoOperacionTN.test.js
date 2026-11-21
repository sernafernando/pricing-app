import { describe, expect, it } from 'vitest';
import { resultadoOperacionTN } from './resultadoOperacionTN';

describe('resultadoOperacionTN', () => {
  it('subtracts the commission and the cost from the amount', () => {
    const r = resultadoOperacionTN({ precio_final_sin_iva: '1000', costo_pesos_sin_iva: '600' }, 10);

    expect(r).toEqual({ sinCosto: false, comision: 100, montoLimpio: 900, ganancia: 300, markup: 0.5 });
  });

  it('leaves ganancia and markup unknown when the API sends no cost (unknown costo SI)', () => {
    const r = resultadoOperacionTN({ precio_final_sin_iva: '1000', costo_pesos_sin_iva: null }, 10);

    expect(r).toEqual({ sinCosto: true, comision: 100, montoLimpio: 900, ganancia: null, markup: null });
  });

  it('treats the older 0 cost as sin costo too, never as a 100% profit', () => {
    expect(resultadoOperacionTN({ precio_final_sin_iva: '1000', costo_pesos_sin_iva: 0 }, 10).ganancia).toBeNull();
  });

  it('keeps a credit note negative', () => {
    const r = resultadoOperacionTN({ precio_final_sin_iva: '-1000', costo_pesos_sin_iva: '-600' }, 10);

    expect(r.ganancia).toBe(-300);
  });
});
