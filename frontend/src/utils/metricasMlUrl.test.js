import { describe, it, expect } from 'vitest';
import { defaultSortFor, defaultView, readMetricasUrl, sortOnGroupChange, writeMetricasUrl } from './metricasMlUrl';

const TODAY = new Date(2026, 9, 27);
const SORT_KEYS = new Set(['gross', 'units_30d', 'title']);
const read = (query) => readMetricasUrl(new URLSearchParams(query), { sortKeys: SORT_KEYS, today: TODAY });
const DEFAULTS = defaultView(TODAY);

describe('metricasMlUrl', () => {
  it('reads an empty query as the default view, and writes nothing for it', () => {
    expect(read('')).toEqual(DEFAULTS);
    expect(DEFAULTS.range).toEqual({ desde: '2026-10-01', hasta: '2026-10-27', filtro: 'mesActual' });
    expect(writeMetricasUrl(DEFAULTS).toString()).toBe('');
  });

  it('round-trips the period, the grouping, every filter and the sort', () => {
    const view = {
      ...DEFAULTS,
      range: { desde: '2026-09-01', hasta: '2026-09-15', filtro: 'custom' },
      compararCon: 'anio_anterior',
      groupBy: 'group',
      dimension: 'categoria',
      searchQuery: 'epson l3250',
      productFilters: { marcas: ['Epson', 'HP'], categorias: ['Impresoras'], subcategorias: [12, 40], pms: [7] },
      storeFilter: '57997,2645',
      pubStatus: ['active', 'under_review'],
      pubType: ['premium'],
      pubStatusExclude: ['closed'],
      pubTypeExclude: ['catalogo'],
      alerts: ['sin_ventas_30d'],
      stock: ['con_stock'],
      stockExclude: ['sin_dato'],
      ageing: ['up_to_30'],
      ageingExclude: ['over_60'],
      soloConVentas: false,
      sort: { key: 'units_30d', desc: false },
    };

    expect(read(writeMetricasUrl(view).toString())).toEqual(view);
  });

  it.each(['marca:TP-Link', 'ean:7791234567890', '*AX55', 'L32*', 'promo:hot sale', 'mla:MLA123'])(
    'round-trips a search with an operator of Publicaciones ML (%s)',
    (searchQuery) => {
      const view = { ...DEFAULTS, searchQuery };
      expect(read(writeMetricasUrl(view).toString())).toEqual(view);
    },
  );

  it('reads a preset period relative to today, so a saved link keeps meaning "the last 7 days"', () => {
    expect(read('periodo=7d').range).toEqual({ desde: '2026-10-21', hasta: '2026-10-27', filtro: '7d' });
    expect(writeMetricasUrl({ ...DEFAULTS, range: { desde: '2026-10-21', hasta: '2026-10-27', filtro: '7d' } }).toString()).toBe(
      'periodo=7d',
    );
  });

  it('keeps the default where a value is unknown, instead of sending it to the board', () => {
    const view = read(
      'periodo=custom&desde=ayer&agrupar=pais&comparar=x&dimension=&orden=drop_table&dir=up&pms=a,3&solo_ventas=quizas' +
        '&estado=active,foo&tipo=bar&alertas=nada&stock=con_stock,x&ageing=old',
    );

    expect(view).toEqual({
      ...DEFAULTS,
      productFilters: { ...DEFAULTS.productFilters, pms: [3] },
      pubStatus: ['active'],
      stock: ['con_stock'],
    });
  });

  it('refuses a custom period on a day the calendar does not have, or backwards', () => {
    expect(read('periodo=custom&desde=2026-02-30&hasta=2026-03-05').range).toEqual(DEFAULTS.range);
    expect(read('periodo=custom&desde=2026-13-01&hasta=2026-13-05').range).toEqual(DEFAULTS.range);
    expect(read('periodo=custom&desde=2026-09-15&hasta=2026-09-01').range).toEqual(DEFAULTS.range);
  });

  it('leaves the params that are not its own where they are', () => {
    const current = new URLSearchParams('utm_source=mail&periodo=7d&marcas=HP');

    const byPublication = { ...DEFAULTS, groupBy: 'publication', sort: defaultSortFor('publication') };
    expect(writeMetricasUrl(byPublication, current).toString()).toBe('utm_source=mail&agrupar=publication');
  });

  // Owner, 2026-11-02: "primero ordene las clásicas, después las 3 cuotas, después las 6, etc" -- where a row is
  // a publication. Product rows mix every type: they keep the gross.
  describe('the listing type order', () => {
    const LISTING = { key: 'listing_kind', desc: false };
    const GROSS = { key: 'gross', desc: true };

    it('is the default sort of the publication grouping only', () => {
      expect(defaultSortFor('publication')).toEqual(LISTING);
      expect(defaultSortFor('product')).toEqual(GROSS);
      expect(defaultSortFor('group')).toEqual(GROSS);
      expect(read('agrupar=publication').sort).toEqual(LISTING);
      expect(writeMetricasUrl({ ...DEFAULTS, groupBy: 'publication', sort: LISTING }).toString()).toBe('agrupar=publication');
      // the gross by publication is no longer the default there: the link says it
      expect(writeMetricasUrl({ ...DEFAULTS, groupBy: 'publication', sort: GROSS }).toString()).toBe(
        'agrupar=publication&orden=gross&dir=desc',
      );
    });

    it('a link may ask for it, but never on the grouped view (the board refuses it there)', () => {
      expect(read('agrupar=publication&orden=listing_kind&dir=desc').sort).toEqual({ key: 'listing_kind', desc: true });
      expect(read('agrupar=group&orden=listing_kind&dir=asc').sort).toEqual(GROSS);
    });

    it('follows the grouping while the sort is the default; a chosen sort stays', () => {
      expect(sortOnGroupChange(GROSS, 'product', 'publication')).toEqual(LISTING);
      expect(sortOnGroupChange(LISTING, 'publication', 'product')).toEqual(GROSS);
      const units = { key: 'units_30d', desc: true };
      expect(sortOnGroupChange(units, 'product', 'publication')).toEqual(units);
      expect(sortOnGroupChange({ key: 'listing_kind', desc: true }, 'publication', 'product')).toEqual({ key: 'listing_kind', desc: true });
      expect(sortOnGroupChange({ key: 'listing_kind', desc: true }, 'publication', 'group')).toEqual(GROSS);
    });
  });
});
