import { describe, it, expect } from 'vitest';
import { readMetricasUrl, writeMetricasUrl } from './metricasMlUrl';

const SORT_KEYS = new Set(['gross', 'units', 'title']);
const read = (query, today = new Date(2026, 9, 27)) => readMetricasUrl(new URLSearchParams(query), { sortKeys: SORT_KEYS, today });

const DEFAULTS = {
  range: { desde: '2026-10-01', hasta: '2026-10-27', filtro: 'mesActual' },
  compararCon: 'periodo_anterior',
  groupBy: 'product',
  dimension: 'marca',
  searchQuery: '',
  productFilters: { marcas: [], categorias: [], subcategorias: [], pms: [] },
  storeFilter: '',
  pubStatus: [],
  pubType: [],
  pubStatusExclude: [],
  pubTypeExclude: [],
  alerts: [],
  stock: [],
  stockExclude: [],
  ageing: [],
  ageingExclude: [],
  soloConVentas: true,
  sort: { key: 'gross', desc: true },
};

describe('metricasMlUrl', () => {
  it('writes nothing for the default view', () => {
    expect(writeMetricasUrl(DEFAULTS).toString()).toBe('');
  });

  it('round-trips the period, the grouping, every filter and the sort', () => {
    const state = {
      ...DEFAULTS,
      range: { desde: '2026-09-01', hasta: '2026-09-15', filtro: 'custom' },
      compararCon: 'anio_anterior',
      groupBy: 'group',
      dimension: 'categoria',
      searchQuery: 'epson l3250',
      productFilters: { marcas: ['Epson', 'HP'], categorias: ['Impresoras'], subcategorias: [12, 40], pms: [7] },
      storeFilter: '57997,2645',
      pubStatus: ['active'],
      pubType: ['premium'],
      pubStatusExclude: ['closed'],
      pubTypeExclude: ['catalogo'],
      alerts: ['sin_ventas_30d'],
      stock: ['con_stock'],
      stockExclude: ['sin_dato'],
      ageing: ['up_to_30'],
      ageingExclude: ['over_60'],
      soloConVentas: false,
      sort: { key: 'units', desc: false },
    };

    expect(read(writeMetricasUrl(state).toString())).toEqual(state);
  });

  it('reads a preset period relative to today, so a saved link keeps meaning "the last 7 days"', () => {
    expect(read('periodo=7d').range).toEqual({ desde: '2026-10-21', hasta: '2026-10-27', filtro: '7d' });
    expect(writeMetricasUrl({ ...DEFAULTS, range: { desde: '2026-10-21', hasta: '2026-10-27', filtro: '7d' } }).toString()).toBe(
      'periodo=7d',
    );
  });

  it('ignores what it does not know instead of sending it to the board', () => {
    const state = read('periodo=custom&desde=ayer&agrupar=pais&comparar=x&dimension=&orden=drop_table&dir=up&pms=a,3&solo_ventas=quizas');

    expect(state.range).toBeUndefined();
    expect(state.groupBy).toBeUndefined();
    expect(state.compararCon).toBeUndefined();
    expect(state.dimension).toBeUndefined();
    expect(state.sort).toBeUndefined();
    expect(state.soloConVentas).toBeUndefined();
    expect(state.productFilters.pms).toEqual([3]);
  });

  it('reads an empty query as the default view', () => {
    expect(read('')).toEqual({ productFilters: { marcas: [], categorias: [], subcategorias: [], pms: [] } });
  });
});
