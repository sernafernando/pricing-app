import { describe, expect, it } from 'vitest';
import { costoSiArs, markupGremioDesdePrecio } from './tiendaGremio';

// Costo SI T3 PR 6 (S13, D1, interfaz §6/§7): the markup shown for a manual Gremio price is over costo SI in pesos
// (`producto.costo_si.costo_ars`), never the list cost (`producto.costo_ars`). Invented data.
const conSi = { costo_ars: 100000, iva: 21, costo_si: { costo: 80, moneda: 'USD', fuente: 'costo_si', costo_ars: 80000 } };

describe('costoSiArs', () => {
  it('reads costo SI in pesos, not the list cost', () => {
    expect(costoSiArs(conSi)).toBe(80000);
  });

  it('is null without costo SI, without pesos or with no positive cost (never the list cost, never 0)', () => {
    expect(costoSiArs({ costo_ars: 100000 })).toBeNull();
    expect(costoSiArs({ costo_ars: 100000, costo_si: null })).toBeNull();
    expect(costoSiArs({ costo_ars: 100000, costo_si: { costo: 80, moneda: 'USD', costo_ars: null } })).toBeNull();
    expect(costoSiArs({ costo_si: { costo: 0, moneda: 'ARS', costo_ars: 0 } })).toBeNull();
  });

  it('an ARS costo SI is its pesos as given', () => {
    expect(costoSiArs({ costo_si: { costo: 50000, moneda: 'ARS', costo_ars: 50000 } })).toBe(50000);
  });
});

describe('markupGremioDesdePrecio', () => {
  it('is over costo SI and inverts the price', () => {
    expect(markupGremioDesdePrecio(80000, 80000 * 1.07 * 1.2)).toBeCloseTo(20, 6);
  });

  it('is null without a cost', () => {
    expect(markupGremioDesdePrecio(null, 100000)).toBeNull();
  });
});
