import { describe, it, expect } from 'vitest';
import { adsCoverageNote } from './metricasMlAds';

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
