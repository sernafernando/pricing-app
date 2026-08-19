import { describe, expect, it } from 'vitest';
import { selectTabItems, computeSummaryCounts, matchesSearch } from './tiendaNubeReconcileHelpers';

describe('selectTabItems', () => {
  const reporte = [
    { ean: '1', verdict: 'FALTA_PUBLICAR' },
    { ean: '2', verdict: 'DUPLICADO' },
  ];
  const baneados = [{ id: 1, ean: '3' }];

  it('returns the full reporte for "todos"', () => {
    expect(selectTabItems('todos', reporte, baneados)).toBe(reporte);
  });

  it('returns baneados for BANLIST, never reporte', () => {
    expect(selectTabItems('BANLIST', reporte, baneados)).toBe(baneados);
  });

  it('filters reporte by verdict for any other tab id', () => {
    expect(selectTabItems('DUPLICADO', reporte, baneados)).toEqual([{ ean: '2', verdict: 'DUPLICADO' }]);
  });
});

describe('computeSummaryCounts', () => {
  it('counts unblocked FALTA_PUBLICAR rows as ready to publish', () => {
    const reporte = [
      { verdict: 'FALTA_PUBLICAR' },
      { verdict: 'FALTA_PUBLICAR', publish_fields_error: 'faltan medidas' },
      { verdict: 'FALTA_PUBLICAR', publish_draft: { blocked: true } },
    ];
    const counts = computeSummaryCounts(reporte);
    expect(counts.readyToPublish).toBe(1);
    expect(counts.bloqueados).toBe(2);
    expect(counts.total).toBe(3);
  });

  it('groups DUPLICADO/MAL_VINCULADO/MAL_PUBLICADO/POR_CORREGIR under necesitanRevision', () => {
    const reporte = [
      { verdict: 'DUPLICADO' },
      { verdict: 'MAL_VINCULADO' },
      { verdict: 'MAL_PUBLICADO' },
      { verdict: 'POR_CORREGIR' },
      { verdict: 'OK' },
      { verdict: 'FALTA_VINCULAR' },
    ];
    const counts = computeSummaryCounts(reporte);
    expect(counts.necesitanRevision).toBe(4);
    expect(counts.total).toBe(6);
  });

  it('returns all-zero counts for an empty report, never throwing', () => {
    expect(computeSummaryCounts([])).toEqual({
      readyToPublish: 0,
      bloqueados: 0,
      necesitanRevision: 0,
      total: 0,
    });
  });
});

describe('matchesSearch', () => {
  const row = { ean: '0123456789', ml_title: 'Auricular Bluetooth XYZ', tn_matches: [{ variant_sku: 'SKU-99' }] };

  it('matches an empty query against any row', () => {
    expect(matchesSearch(row, '')).toBe(true);
    expect(matchesSearch(row, '   ')).toBe(true);
  });

  it('matches by EAN substring', () => {
    expect(matchesSearch(row, '3456')).toBe(true);
  });

  it('matches by title, case-insensitively', () => {
    expect(matchesSearch(row, 'bluetooth')).toBe(true);
  });

  it('matches by TN variant SKU of the first match', () => {
    expect(matchesSearch(row, 'sku-99')).toBe(true);
  });

  it('returns false when nothing matches', () => {
    expect(matchesSearch(row, 'nope')).toBe(false);
  });

  it('never throws on a row with no tn_matches', () => {
    expect(matchesSearch({ ean: '1', ml_title: null, tn_matches: [] }, 'x')).toBe(false);
  });
});
