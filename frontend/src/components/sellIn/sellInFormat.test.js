import { describe, it, expect } from 'vitest';
import { apiMessage, buildSellInParams, formatMonto, sumaManual } from './sellInFormat';

describe('buildSellInParams', () => {
  it('sends only the filters that are set, marcas as CSV', () => {
    expect(
      buildSellInParams({
        aplica: 'si',
        q: '  switch ',
        marcas: ['TP-Link', 'Mercusys'],
        moneda: 'USD',
        estado: 'activa',
        desde: '2026-10-01',
        hasta: '2026-10-31',
      }),
    ).toEqual({
      aplica: 'si',
      q: 'switch',
      marcas: 'TP-Link,Mercusys',
      moneda: 'USD',
      estado: 'activa',
      fecha_desde: '2026-10-01',
      fecha_hasta: '2026-10-31',
    });
  });

  it('drops empty values', () => {
    expect(buildSellInParams({ aplica: '', q: '   ', marcas: [], moneda: '', estado: '', desde: '', hasta: '' })).toEqual({});
  });
});

describe('formatMonto', () => {
  it('prefixes the currency the way the design writes it', () => {
    expect(formatMonto('1000.00', 'ARS')).toBe('$ 1.000,00');
    expect(formatMonto('4500', 'USD')).toBe('USD 4.500,00');
  });

  it('reads a missing value as a dash, never as zero', () => {
    expect(formatMonto(null, 'ARS')).toBe('—');
  });
});

describe('sumaManual', () => {
  it('adds the manual amounts in cents so 0.1 + 0.2 is 0.3', () => {
    expect(sumaManual(['0.1', '0.2'])).toBe(0.3);
    expect(sumaManual(['', '5'])).toBe(5);
  });
});

describe('apiMessage', () => {
  it('reads the standard error envelope, then a plain detail, then the fallback', () => {
    expect(apiMessage({ response: { data: { error: { message: 'Falta el tipo de cambio' } } } }, 'x')).toBe('Falta el tipo de cambio');
    expect(apiMessage({ response: { data: { detail: 'La compra 9 no existe' } } }, 'x')).toBe('La compra 9 no existe');
    expect(apiMessage({ response: { data: { detail: [{ msg: 'field' }] } } }, 'x')).toBe('x');
    expect(apiMessage(new Error('network'), 'x')).toBe('x');
  });
});
