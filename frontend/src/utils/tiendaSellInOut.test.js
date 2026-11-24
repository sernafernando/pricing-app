import { describe, it, expect } from 'vitest';
import { tiendaSellInOutDe } from './tiendaSellInOut';

const SELL_IN_OUT = {
  sell_out: { gremio: { monto_unit: 500, campana_ids: [3] } },
  markups_sell_in: {},
  markups_sell_in_out: { gremio: 38.89 },
};

describe('tiendaSellInOutDe — the Tienda row sell out of one markup key', () => {
  it("gives the key's sell out and the row's markups", () => {
    expect(tiendaSellInOutDe(SELL_IN_OUT, 'gremio')).toEqual({
      sell_out: { monto_unit: 500, campana_ids: [3] },
      markups_sell_in_out: { gremio: 38.89 },
    });
  });

  it('gives no sell out for a key without one', () => {
    expect(tiendaSellInOutDe(SELL_IN_OUT, 'web_transf').sell_out).toBeNull();
  });

  it('never passes on a sell in, even from an older payload that carries one (costo SI T5 PR B)', () => {
    const viejo = { ...SELL_IN_OUT, sell_in: { compra_item_id: 7, descuento_unit: 1000, costo: 9000 } };
    expect(tiendaSellInOutDe(viejo, 'gremio')).not.toHaveProperty('sell_in');
  });

  it('is null for a row without sell_in_out', () => {
    expect(tiendaSellInOutDe(null, 'gremio')).toBeNull();
  });
});
