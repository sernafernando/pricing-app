import { describe, expect, it } from 'vitest';
import { valueOf } from './stockAuditRows';

// L4.7: a publication's Full is valued at its node's costo SI; `costo` is the list cost, shown only.
describe('valueOf', () => {
  it('values the units at costo SI, not at the list cost', () => {
    const node = { costo: 30, moneda_costo: 'USD', costo_si: 20, costo_si_moneda: 'USD' };
    expect(valueOf(5, node, 1000)).toEqual({ usd: 100, ars: 100000 });
  });

  it('a costo SI in pesos converts to dollars at the rate', () => {
    const node = { costo: 9000, moneda_costo: 'ARS', costo_si: 8000, costo_si_moneda: 'ARS' };
    expect(valueOf(2, node, 1000)).toEqual({ usd: 16, ars: 16000 });
  });

  it('an unknown costo SI is unknown, never the list cost nor 0', () => {
    const node = { costo: 30, moneda_costo: 'USD', costo_si: null, costo_si_moneda: null };
    expect(valueOf(5, node, 1000)).toEqual({ usd: null, ars: null });
  });
});
