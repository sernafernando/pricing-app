/**
 * sellOutReparto: the pure rules of a `monto_total` campaign's split (T26d), mirroring the API's (`reparto.validar`).
 */
import { describe, it, expect } from 'vitest';
import { CAMPANA_MONTO_TOTAL } from './sellOutFixtures';
import {
  MODO_MONTO,
  MODO_PORCENTAJE,
  aCentavos,
  centavosAjenos,
  centavosDeFila,
  errorDeReparto,
  filasDeCampana,
  totalesDeReparto,
} from './sellOutReparto';

const fila = (modo, valor, codigo = 'ABC') => ({ itemId: 1, codigo, descripcion: null, modo, valor });

describe('sellOutReparto', () => {
  it('rounds cents half away from zero, also for a negative total', () => {
    expect(aCentavos('0.005')).toBe(1);
    expect(aCentavos('-0.005')).toBe(-1);
    expect(centavosDeFila(aCentavos('-100.01'), fila(MODO_PORCENTAJE, '50'))).toBe(-5001);
    expect(centavosDeFila(aCentavos('100.01'), fila(MODO_PORCENTAJE, '50'))).toBe(5001);
    expect(centavosDeFila(10000, fila(MODO_PORCENTAJE, ''))).toBeNull();
  });

  it('an empty or 0 share needs a value', () => {
    expect(errorDeReparto('1000', [fila(MODO_MONTO, '')], 'ARS')).toBe('El producto ABC necesita un porcentaje o un monto de reparto');
    expect(errorDeReparto('1000', [fila(MODO_PORCENTAJE, '0')], 'ARS')).toBe('El producto ABC necesita un porcentaje o un monto de reparto');
  });

  it('a % share is over 0 and up to 100', () => {
    const mensaje = 'El porcentaje de reparto tiene que ser mayor a 0 y hasta 100';
    expect(errorDeReparto('1000', [fila(MODO_PORCENTAJE, '-5')], 'ARS')).toBe(mensaje);
    expect(errorDeReparto('1000', [fila(MODO_PORCENTAJE, '100.5')], 'ARS')).toBe(mensaje);
    expect(errorDeReparto('1000', [fila(MODO_PORCENTAJE, '100')], 'ARS')).toBeNull();
    expect(errorDeReparto('-1000', [fila(MODO_PORCENTAJE, '100')], 'ARS')).toBeNull();
  });

  it('a fixed share has the total sign', () => {
    expect(errorDeReparto('-1000', [fila(MODO_MONTO, '10')], 'ARS')).toBe('El reparto del producto ABC tiene que tener el signo del monto total');
    expect(errorDeReparto('-1000', [fila(MODO_MONTO, '-10')], 'ARS')).toBeNull();
  });

  it('compares the sum before rounding, like the API: two 50 % shares of 100,01 fit', () => {
    const filas = [fila(MODO_PORCENTAJE, '50', 'A'), { ...fila(MODO_PORCENTAJE, '50', 'B'), itemId: 2 }];
    expect(errorDeReparto('100.01', filas, 'ARS')).toBeNull();
    expect(totalesDeReparto('100.01', filas)).toEqual({ asignado: 100.01, sinAsignar: 0 });
    const conFijo = [...filas.slice(0, 1), { ...fila(MODO_MONTO, '50.01', 'B'), itemId: 2 }];
    // 50,005 + 50,01 = 100,015 > 100,01: refused, with the exact amounts as the API's message (`_importe`) gives them
    expect(errorDeReparto('100.01', conFijo, 'ARS')).toBe('El reparto ($ 100,015) supera el monto total ($ 100,01) en $ 0,005');
  });

  it('a sub-cent excess never reads 0,00: exact amounts when they have more decimals than cents', () => {
    const filas = [fila(MODO_PORCENTAJE, '50.0001', 'A'), { ...fila(MODO_MONTO, '50.00', 'B'), itemId: 2 }];
    expect(errorDeReparto('100.00', filas, 'ARS')).toBe('El reparto ($ 100,0001) supera el monto total ($ 100,00) en $ 0,0001');
    const grande = [fila(MODO_MONTO, '2100000', 'A')];
    expect(errorDeReparto('-2000000', [{ ...grande[0], valor: '-2100000' }], 'ARS')).toBe(
      'El reparto ($ -2.100.000,00) supera el monto total ($ -2.000.000,00) en $ 100.000,00',
    );
  });

  it('a user who sees every share holds no other brands\' money, whatever the per-share rounding', () => {
    // The server's `asignado` sums each share rounded to cents (`reparto._cargada`): 50,01 + 50,01 = 100,02.
    const dosMitades = {
      ...CAMPANA_MONTO_TOTAL,
      monto_total: '100.01',
      items: [
        { item_id: 1, codigo: 'A', reparto_porcentaje: '50.0000', reparto_monto: null },
        { item_id: 2, codigo: 'B', reparto_porcentaje: '50.0000', reparto_monto: null },
      ],
      resumen: { ...CAMPANA_MONTO_TOTAL.resumen, reparto: { asignado: '100.02', asignado_sin_ventas: '0.00', sin_asignar: '-0.01', motivo: null } },
    };
    expect(centavosAjenos(dosMitades)).toBe(0);
    expect(errorDeReparto('100.01', filasDeCampana(dosMitades), 'ARS', centavosAjenos(dosMitades))).toBeNull();
    // 3 × 33,3333 % of 100,00 = 33,33 each once rounded: the server says 99,99.
    const tercios = {
      ...dosMitades,
      monto_total: '100.00',
      items: [1, 2, 3].map((id) => ({ item_id: id, codigo: `P${id}`, reparto_porcentaje: '33.3333', reparto_monto: null })),
      resumen: { ...dosMitades.resumen, reparto: { asignado: '99.99', asignado_sin_ventas: '0.00', sin_asignar: '0.01', motivo: null } },
    };
    expect(centavosAjenos(tercios)).toBe(0);
  });

  it('the shares the user cannot see count in the totals and the guard', () => {
    // Server: 1.700.000 assigned; this user holds the 60 % share only (1.200.000): 500.000 belong to other brands.
    const campana = { ...CAMPANA_MONTO_TOTAL, items: [CAMPANA_MONTO_TOTAL.items[0]] };
    const ajenos = centavosAjenos(campana);
    expect(ajenos).toBe(50000000);
    const filas = filasDeCampana(campana);
    expect(totalesDeReparto('2000000.00', filas, ajenos)).toEqual({ asignado: 1700000, sinAsignar: 300000 });
    const mas = [{ ...filas[0], valor: '80' }];
    expect(errorDeReparto('2000000.00', mas, 'ARS', ajenos)).toBe(
      'El reparto ($ 2.100.000,00) supera el monto total ($ 2.000.000,00) en $ 100.000,00',
    );
  });

  it('with every share visible, or no server amount, nothing is somebody else’s', () => {
    expect(centavosAjenos(CAMPANA_MONTO_TOTAL)).toBe(0);
    const sinMonto = { ...CAMPANA_MONTO_TOTAL, resumen: { ...CAMPANA_MONTO_TOTAL.resumen, reparto: { asignado: null, motivo: 'x' } } };
    expect(centavosAjenos(sinMonto)).toBe(0);
  });
});
