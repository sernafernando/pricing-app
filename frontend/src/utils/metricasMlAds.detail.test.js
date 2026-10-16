import { describe, it, expect } from 'vitest';
import { adsCoverageNote, adsRowKind, unattributedLines } from './metricasMlAds';

const day = (d) => ({ source: 'product_ads', advertiser_id: 1, day: d, status: null });

describe('adsCoverageNote', () => {
  it('says nothing when the API sent no coverage', () => {
    expect(adsCoverageNote(null)).toBeNull();
  });

  it('flags a ledger with no trusted day at all, never as zero spend', () => {
    const note = adsCoverageNote({ available: false, data_through: null, missing_days: [], mismatch_days: [] });
    expect(note).toEqual({ tone: 'warn', text: 'Sin datos de Ads para el período' });
  });

  it('reads "ok" when the data is whole', () => {
    const note = adsCoverageNote({ available: true, data_through: '2026-10-13', missing_days: [], mismatch_days: [] });
    expect(note).toEqual({ tone: 'ok', text: 'Datos de Ads hasta el 13/10' });
  });

  it('does not read as ok when the ledger has data but no cut-off date', () => {
    const note = adsCoverageNote({ available: true, data_through: null, missing_days: [], mismatch_days: [] });
    expect(note).toEqual({ tone: 'warn', text: 'Datos de Ads sin fecha de corte' });
  });

  it('counts the missing and the mismatched days', () => {
    const note = adsCoverageNote({
      available: true,
      data_through: '2026-10-13',
      missing_days: [day('2026-10-14'), day('2026-10-15')],
      mismatch_days: [day('2026-10-10')],
    });
    expect(note).toEqual({
      tone: 'warn',
      text: 'Datos de Ads hasta el 13/10 · faltan 2 días · 1 día con diferencias',
    });
  });
});

describe('unattributedLines', () => {
  const unattributed = {
    sin_producto_cost: 412380,
    account_level: { display: { cost_api: 1512500, cost_net: 1250000, subtracted: false }, brand: { cost: 380500, subtracted: false } },
  };

  it('lists Display, Brand and Ads sin producto; sin producto is subtracted at every position', () => {
    expect(unattributedLines(unattributed).map((l) => [l.key, l.amount, l.subtracted])).toEqual([
      ['display', 1250000, false],
      ['brand', 380500, false],
      ['sin_producto', 412380, true],
    ]);
  });

  it('marks Display and Brand as subtracted when the API says so', () => {
    const on = { ...unattributed, account_level: { display: { ...unattributed.account_level.display, subtracted: true }, brand: { cost: 380500, subtracted: true } } };
    expect(unattributedLines(on).map((l) => l.subtracted)).toEqual([true, true, true]);
  });
});

describe('adsRowKind', () => {
  it('tells the "sin producto" row and an ads-only row from a normal one', () => {
    expect(adsRowKind({ product_item_id: 0, units: 0, ads: { cost: 5 } })).toBe('sin_producto');
    expect(adsRowKind({ product_item_id: 7, units: 0, ads: { cost: 5 } })).toBe('solo_ads');
    expect(adsRowKind({ product_item_id: 7, units: 3, ads: { cost: 5 } })).toBeNull();
    expect(adsRowKind({ product_item_id: 7, units: 0 })).toBeNull();
  });
});
