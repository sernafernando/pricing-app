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
