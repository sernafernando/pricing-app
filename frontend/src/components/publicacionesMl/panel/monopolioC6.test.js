import { describe, expect, it } from 'vitest';
import { computeMonopolioC6, minRivalPriceArs, monopolioFromSnapshotAndCriterios } from './monopolioC6';

describe('monopolioC6', () => {
  it('computes raise when winning with gap ≥ min', () => {
    const out = computeMonopolioC6({
      c6Activo: true,
      ourPrice: 10000,
      segundoPrecio: 16000,
      gapMin: 5000,
      distanciaObjetivo: 100,
    });
    expect(out).toEqual({
      our_price: 10000,
      segundo_precio: 16000,
      gap: 6000,
      precio_objetivo: 15900,
      distancia_objetivo: 100,
    });
  });

  it('ignores unchecked rivals for min price', () => {
    expect(
      minRivalPriceArs(
        [
          { item_id: 'MLA1', price_ars: 10000 },
          { item_id: 'R1', price_ars: 11000 },
          { item_id: 'R2', price_ars: 16000 },
        ],
        'MLA1',
        ['R1'],
      ),
    ).toBe(16000);
  });

  it('builds from snapshot + criterios', () => {
    const out = monopolioFromSnapshotAndCriterios(
      'MLA1',
      {
        same_bucket: [
          { item_id: 'MLA1', price_ars: 10000 },
          { item_id: 'R2', price_ars: 16000 },
        ],
      },
      { c6_activo: true, c6_gap_min: 5000, c6_distancia_objetivo: 100, sellers_excluidos: [] },
    );
    expect(out?.precio_objetivo).toBe(15900);
  });
});
