import { describe, expect, it } from 'vitest';
import { restanteDeTope } from './sellInBonoValores';

const entero = (n) => String(n);
const monto = (v, moneda) => `${moneda} ${v}`;
const BONO = { moneda: 'ARS', tope_unidades: 2, tope_monto: '20.00', tope_unidades_restantes: 1, tope_monto_restante: '10.00' };

describe('restanteDeTope', () => {
  it('a shared cap shows what is left of it', () => {
    expect(restanteDeTope({ ...BONO, tope_por_tienda: false }, entero, monto)).toBe('1 u de 2 · ARS 10.00 de ARS 20.00');
  });

  it('a per-store cap says so, and what is left is between every store', () => {
    expect(restanteDeTope({ ...BONO, tope_por_tienda: true }, entero, monto)).toBe(
      '1 u de 2 por tienda · ARS 10.00 de ARS 20.00 por tienda, entre todas las tiendas',
    );
  });

  it('is null without a cap', () => {
    expect(restanteDeTope({ ...BONO, tope_unidades: null, tope_monto: null, tope_por_tienda: true }, entero, monto)).toBeNull();
  });
});
