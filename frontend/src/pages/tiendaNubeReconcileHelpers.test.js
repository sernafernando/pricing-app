import { describe, expect, it } from 'vitest';
import {
  selectTabItems,
  computeSummaryCounts,
  matchesSearch,
  matchesSummaryFilter,
  resolvePrimaryAction,
  pickEditorTnMatch,
  resolveSecondaryActions,
  primaryTnMatch,
} from './tiendaNubeReconcileHelpers';

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

describe('matchesSummaryFilter', () => {
  it('"ready" matches only unblocked FALTA_PUBLICAR rows', () => {
    expect(matchesSummaryFilter({ verdict: 'FALTA_PUBLICAR' }, 'ready')).toBe(true);
    expect(matchesSummaryFilter({ verdict: 'FALTA_PUBLICAR', publish_fields_error: 'x' }, 'ready')).toBe(false);
    expect(matchesSummaryFilter({ verdict: 'MAL_VINCULADO' }, 'ready')).toBe(false);
  });

  it('"bloqueados" matches only blocked FALTA_PUBLICAR rows', () => {
    expect(matchesSummaryFilter({ verdict: 'FALTA_PUBLICAR', publish_draft: { blocked: true } }, 'bloqueados')).toBe(true);
    expect(matchesSummaryFilter({ verdict: 'FALTA_PUBLICAR' }, 'bloqueados')).toBe(false);
  });

  it('"revision" matches the 4 review verdicts only', () => {
    for (const verdict of ['DUPLICADO', 'MAL_VINCULADO', 'MAL_PUBLICADO', 'POR_CORREGIR']) {
      expect(matchesSummaryFilter({ verdict }, 'revision')).toBe(true);
    }
    expect(matchesSummaryFilter({ verdict: 'FALTA_PUBLICAR' }, 'revision')).toBe(false);
  });

  it('"total" matches every row', () => {
    expect(matchesSummaryFilter({ verdict: 'OK' }, 'total')).toBe(true);
  });
});

function despublicarTargetProductId(row) {
  const published = row.tn_matches.find((tn) => tn.published === true);
  if (published) return published.product_id;
  return row.tn_matches[0]?.product_id ?? null;
}

describe('resolvePrimaryAction', () => {
  it('is Publicar for FALTA_PUBLICAR when the operator can publish', () => {
    expect(resolvePrimaryAction({ verdict: 'FALTA_PUBLICAR' }, true)).toEqual({
      id: 'publicar',
      label: 'Publicar',
    });
  });

  it('is Revisar for FALTA_PUBLICAR without the publish permission', () => {
    expect(resolvePrimaryAction({ verdict: 'FALTA_PUBLICAR' }, false)).toEqual({
      id: 'revisar',
      label: 'Revisar',
    });
  });

  it('is Vincular for FALTA_VINCULAR regardless of permission', () => {
    expect(resolvePrimaryAction({ verdict: 'FALTA_VINCULAR' }, false)).toEqual({
      id: 'vincular',
      label: 'Vincular',
    });
  });

  it('is null for verdicts with no primary action (e.g. OK, MAL_PUBLICADO)', () => {
    expect(resolvePrimaryAction({ verdict: 'OK' }, true)).toBeNull();
    expect(resolvePrimaryAction({ verdict: 'MAL_PUBLICADO' }, true)).toBeNull();
  });
});

describe('pickEditorTnMatch', () => {
  it('prefers the match TN reports as published: true', () => {
    const row = {
      tn_matches: [
        { product_id: 1, tn_admin_url: 'https://tn/1', published: false },
        { product_id: 2, tn_admin_url: 'https://tn/2', published: true },
      ],
    };
    expect(pickEditorTnMatch(row)).toEqual(row.tn_matches[1]);
  });

  it('falls back to the first match carrying a URL when none is published', () => {
    const row = {
      tn_matches: [
        { product_id: 1, tn_admin_url: null, published: false },
        { product_id: 2, tn_admin_url: 'https://tn/2', published: false },
      ],
    };
    expect(pickEditorTnMatch(row)).toEqual(row.tn_matches[1]);
  });

  it('returns null when no match carries a URL', () => {
    expect(pickEditorTnMatch({ tn_matches: [{ product_id: 1, tn_admin_url: null }] })).toBeNull();
    expect(pickEditorTnMatch({ tn_matches: [] })).toBeNull();
  });
});

describe('resolveSecondaryActions', () => {
  const perms = (overrides = {}) => ({
    canBanlist: true,
    canPublish: true,
    despublicarTargetProductId,
    ...overrides,
  });

  it('includes Banear for FALTA_PUBLICAR when canBanlist is true', () => {
    const row = { verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [] };
    const actions = resolveSecondaryActions(row, perms());
    expect(actions.some((a) => a.id === 'banear')).toBe(true);
  });

  it('includes Banear for FALTA_VINCULAR too, not only FALTA_PUBLICAR', () => {
    const row = { verdict: 'FALTA_VINCULAR', despublicar: false, tn_matches: [] };
    const actions = resolveSecondaryActions(row, perms());
    expect(actions.some((a) => a.id === 'banear')).toBe(true);
  });

  it('hides Banear without canBanlist', () => {
    const row = { verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [] };
    const actions = resolveSecondaryActions(row, perms({ canBanlist: false }));
    expect(actions.some((a) => a.id === 'banear')).toBe(false);
  });

  it('hides Banear on verdicts other than FALTA_PUBLICAR/FALTA_VINCULAR', () => {
    const row = { verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [] };
    const actions = resolveSecondaryActions(row, perms());
    expect(actions.some((a) => a.id === 'banear')).toBe(false);
  });

  it('includes Despublicar with its resolved target product id when flagged and permitted', () => {
    const row = {
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 555, published: true }],
    };
    const actions = resolveSecondaryActions(row, perms());
    expect(actions.find((a) => a.id === 'despublicar')).toEqual({
      id: 'despublicar',
      label: 'Despublicar',
      productId: 555,
    });
  });

  it('hides Despublicar without canPublish', () => {
    const row = {
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 555, published: true }],
    };
    const actions = resolveSecondaryActions(row, perms({ canPublish: false }));
    expect(actions.some((a) => a.id === 'despublicar')).toBe(false);
  });

  it('hides Despublicar when the row is not flagged despublicar', () => {
    const row = { verdict: 'MAL_VINCULADO', despublicar: false, tn_matches: [{ product_id: 555 }] };
    const actions = resolveSecondaryActions(row, perms());
    expect(actions.some((a) => a.id === 'despublicar')).toBe(false);
  });

  it('includes Editar en TN with the resolved match href when available', () => {
    const row = {
      verdict: 'MAL_PUBLICADO',
      despublicar: false,
      tn_matches: [{ product_id: 9, tn_admin_url: 'https://tn/9', published: true }],
    };
    const actions = resolveSecondaryActions(row, perms());
    expect(actions.find((a) => a.id === 'editar_tn')).toEqual({
      id: 'editar_tn',
      label: 'Editar en TN',
      href: 'https://tn/9',
      productId: 9,
    });
  });

  it('omits Editar en TN when no match has a URL', () => {
    const row = { verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [] };
    const actions = resolveSecondaryActions(row, perms());
    expect(actions.some((a) => a.id === 'editar_tn')).toBe(false);
  });
});

describe('primaryTnMatch', () => {
  it('returns null when there are no matches', () => {
    expect(primaryTnMatch({ tn_matches: [] })).toBeNull();
    expect(primaryTnMatch({})).toBeNull();
  });

  it('prefers the match TN reports as published: true', () => {
    const row = {
      tn_matches: [
        { product_id: 1, variant_id: 1, published: false },
        { product_id: 2, variant_id: 2, published: true },
      ],
    };
    expect(primaryTnMatch(row)).toEqual({ product_id: 2, variant_id: 2, published: true });
  });

  it('falls back to the first match when none is published: true', () => {
    const row = {
      tn_matches: [
        { product_id: 1, variant_id: 1, published: null },
        { product_id: 2, variant_id: 2, published: false },
      ],
    };
    expect(primaryTnMatch(row)).toEqual({ product_id: 1, variant_id: 1, published: null });
  });

  it('does not require a tn_admin_url, unlike pickEditorTnMatch', () => {
    const row = { tn_matches: [{ product_id: 1, variant_id: 1, published: true }] };
    expect(primaryTnMatch(row)).toEqual({ product_id: 1, variant_id: 1, published: true });
    expect(pickEditorTnMatch(row)).toBeNull();
  });
});
