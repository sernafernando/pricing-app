import { describe, expect, it } from 'vitest';
import { CATALOG_SNAPSHOT_MAX_AGE_MS, catalogSnapshotIsFresh, minRivalPriceArs } from './monopolioC6';

describe('catalog helpers (C2)', () => {
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

  it('matches excluded sellers by seller_id', () => {
    expect(
      minRivalPriceArs(
        [
          { item_id: 'MLA1', price_ars: 10000 },
          { item_id: 'R1', seller_id: 'S1', price_ars: 11000 },
          { item_id: 'R2', seller_id: 'S2', price_ars: 16000 },
        ],
        'MLA1',
        ['S1'],
      ),
    ).toBe(16000);
  });

  it('treats stale catalog snapshots as not fresh', () => {
    const staleIso = new Date(Date.now() - CATALOG_SNAPSHOT_MAX_AGE_MS - 1000).toISOString();
    expect(catalogSnapshotIsFresh({ fetch_status: 'ok', fecha_consulta: staleIso })).toBe(false);
    expect(catalogSnapshotIsFresh({ fetch_status: 'ok', fecha_consulta: new Date().toISOString() })).toBe(true);
  });
});
