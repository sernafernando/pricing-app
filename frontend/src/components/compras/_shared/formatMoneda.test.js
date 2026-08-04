import { describe, it, expect } from 'vitest';
import { formatMoneda, formatMonedaErp, monedaDeCurrId } from './formatMoneda';

/**
 * `curr_id_transaction` is the ERP's own currency on a factura / NC. The mapper
 * mirrors the backend authority `_curr_id_a_moneda`
 * (backend/app/services/pedidos_service.py) — including the fact that an
 * unrecognised id maps to NOTHING rather than to a default currency.
 */
describe('monedaDeCurrId — ERP curr_id_transaction mapping', () => {
  it('maps 1 to ARS (ERP convention)', () => {
    expect(monedaDeCurrId(1)).toBe('ARS');
  });

  it('maps 2 to USD (ERP convention)', () => {
    expect(monedaDeCurrId(2)).toBe('USD');
  });

  it('maps null to null — never to a default currency', () => {
    // Defaulting an unknown currency to ARS is precisely the bug this mapper
    // exists to prevent: the caller MUST handle null explicitly.
    expect(monedaDeCurrId(null)).toBeNull();
    expect(monedaDeCurrId(undefined)).toBeNull();
  });

  it('maps an unknown id to null', () => {
    expect(monedaDeCurrId(3)).toBeNull();
    expect(monedaDeCurrId(0)).toBeNull();
    expect(monedaDeCurrId(-1)).toBeNull();
    expect(monedaDeCurrId('no-es-un-id')).toBeNull();
  });

  it('accepts the id as a numeric string, like a JSON payload may carry it', () => {
    expect(monedaDeCurrId('1')).toBe('ARS');
    expect(monedaDeCurrId('2')).toBe('USD');
  });

  it('never returns a currency for the empty string', () => {
    // Number('') is 0, which must not fall through to any currency.
    expect(monedaDeCurrId('')).toBeNull();
  });
});

describe('formatMonedaErp — formats an ERP amount in its OWN currency', () => {
  it('formats an ARS document with the ARS symbol', () => {
    expect(formatMonedaErp(1500000, 1)).toBe('$1.500.000,00');
  });

  it('formats a USD document with the USD symbol', () => {
    expect(formatMonedaErp(1000, 2)).toBe('US$1.000,00');
  });

  it('renders no currency symbol at all when the currency is unknown', () => {
    const salida = formatMonedaErp(1500000, null);

    expect(salida).toBe('1.500.000,00 (moneda desconocida)');
    // The whole point: no confident-but-possibly-wrong symbol.
    expect(salida).not.toContain('$');
  });

  it('renders no currency symbol for an unrecognised curr_id either', () => {
    expect(formatMonedaErp(250.5, 7)).toBe('250,50 (moneda desconocida)');
  });

  it('matches formatMoneda exactly for known currencies', () => {
    // The ERP formatter must not drift from the module-wide convention.
    expect(formatMonedaErp(1500000, 1)).toBe(formatMoneda(1500000, 'ARS'));
    expect(formatMonedaErp(1500000, 2)).toBe(formatMoneda(1500000, 'USD'));
  });
});
