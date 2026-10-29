import { describe, expect, it } from 'vitest';
import { sellInOrigen } from './sellInOrigen';

describe('sellInOrigen', () => {
  it('names the units left of a purchase lot', () => {
    expect(sellInOrigen({ compra_item_id: 901, bono_id: null, bono_ids: [], unidades_restantes: 12 })).toBe(
      'Unidades restantes del lote: 12',
    );
  });

  it('names one % of cost bonus', () => {
    expect(sellInOrigen({ compra_item_id: null, bono_id: 4, bono_ids: [4], unidades_restantes: null })).toBe(
      'Bono #4 sobre el costo',
    );
  });

  it('names every stacked % of cost bonus in order', () => {
    expect(sellInOrigen({ compra_item_id: null, bono_id: 4, bono_ids: [4, 7], unidades_restantes: null })).toBe(
      'Bonos #4, #7 sobre el costo',
    );
  });

  it('falls back to bono_id when the payload has no bono_ids', () => {
    expect(sellInOrigen({ compra_item_id: null, bono_id: 4, unidades_restantes: null })).toBe('Bono #4 sobre el costo');
  });
});
