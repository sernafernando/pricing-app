/**
 * usePublicacionesMLFilters (publicaciones-ml-vista P11a.T2, S9.1): every
 * filter lives in the URL, so a shared link or a reload shows the same list.
 */
import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import {
  buildExportParams,
  usePublicacionesMLFilters,
  buildItemsParams,
  AGRUPAR_DIMENSIONS,
  FILTER_KEYS,
  PAGE_SIZE,
  effectiveSort,
  effectiveProductSort,
  effectiveSortKeys,
  effectiveProductSortKeys,
  nextSort,
  buildProductsParams,
  buildKpiParams,
  buildProductIdsParams,
  hasMarkupFilter,
  PRESENCE_VALUES,
  PRICE_MODES,
  sinMlaUpdates,
} from './usePublicacionesMLFilters';
import { DIMENSION_OPTIONS } from '../utils/metricasMlLevels';

const setup = (url = '/', permissions = undefined) => {
  const wrapper = ({ children }) => <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>;
  return renderHook(
    () => ({ hook: usePublicacionesMLFilters(permissions), search: useLocation().search }),
    { wrapper },
  );
};

describe('reading the URL', () => {
  it('has neutral defaults', () => {
    const { result } = setup('/');
    const f = result.current.hook.filters;
    expect(f.q).toBe('');
    expect(f.vista).toBe('publicacion');
    expect(f.estado).toEqual([]);
    expect(f.pagina).toBe(1);
    expect(f.sel).toBe('');
    expect(f.orden).toBe('');
  });

  it('parses every param of the contract', () => {
    const url =
      '/?q=router&vista=agrupado&estado=active,paused&estado_excluir=closed&tiendas=57997,none' +
      '&marcas=TP-LINK,EPSON&categorias=Redes&subcategorias=12,13&pms=4&familia=998' +
      '&tipo=full,catalogo&vinculo=auto&stock=full_sin_stock&evento=price_changed&evento_desde=7d' +
      '&orden=precio&dir=asc&pagina=3&sel=MLA123&tab=eventos';
    const f = setup(url).result.current.hook.filters;
    expect(f).toMatchObject({
      q: 'router',
      vista: 'agrupado',
      estado: ['active', 'paused'],
      estado_excluir: ['closed'],
      tiendas: ['57997', 'none'],
      marcas: ['TP-LINK', 'EPSON'],
      categorias: ['Redes'],
      subcategorias: ['12', '13'],
      pms: ['4'],
      familia: '998',
      tipo: ['full', 'catalogo'],
      vinculo: ['auto'],
      stock: ['full_sin_stock'],
      evento: ['price_changed'],
      evento_desde: '7d',
      orden: 'precio',
      dir: 'asc',
      pagina: 3,
      sel: 'MLA123',
      tab: 'eventos',
    });
  });

  it('reads the page size from `limite`, only the sizes the backend allows', () => {
    expect(setup('/?limite=100').result.current.hook.filters.limite).toBe(100);
    expect(setup('/?limite=200').result.current.hook.filters.limite).toBe(200);
    expect(setup('/?limite=500').result.current.hook.filters.limite).toBe(500);
    // Productos' "Todos".
    expect(setup('/?limite=9999').result.current.hook.filters.limite).toBe(9999);
    expect(setup('/?limite=1000').result.current.hook.filters.limite).toBe(PAGE_SIZE);
    expect(setup('/').result.current.hook.filters.limite).toBe(PAGE_SIZE);
  });

  it('falls back on an unknown vista, a bad dir and a bad page', () => {
    const f = setup('/?vista=otra&dir=up&pagina=-2').result.current.hook.filters;
    expect(f.vista).toBe('publicacion');
    expect(f.dir).toBe('');
    expect(f.pagina).toBe(1);
  });
});

describe('writing the URL', () => {
  it('round-trips: what is set is what is read back', () => {
    const { result } = setup('/');
    act(() => result.current.hook.setFilters({ q: 'router', estado: ['active'], tiendas: ['57997', 'none'] }));
    expect(result.current.hook.filters).toMatchObject({
      q: 'router',
      estado: ['active'],
      tiendas: ['57997', 'none'],
    });
    expect(new URLSearchParams(result.current.search).get('tiendas')).toBe('57997,none');
  });

  it('drops a param when it is emptied instead of writing `q=`', () => {
    const { result } = setup('/?q=router&estado=active');
    act(() => result.current.hook.setFilters({ q: '', estado: [] }));
    expect(result.current.search).toBe('');
  });

  it('changing a filter goes back to page 1 and closes the selection', () => {
    const { result } = setup('/?pagina=4&sel=MLA1&tab=eventos&estado=active');
    act(() => result.current.hook.setFilters({ estado: ['paused'] }));
    const params = new URLSearchParams(result.current.search);
    expect(params.has('pagina')).toBe(false);
    expect(params.has('sel')).toBe(false);
    expect(params.has('tab')).toBe(false);
    expect(params.get('estado')).toBe('paused');
  });

  it('reads and writes the product panel (`prod`) like the selection', () => {
    const { result } = setup('/?estado=active');
    expect(result.current.hook.filters.prod).toBe('');
    act(() => result.current.hook.setFilters({ prod: '4101' }));
    expect(result.current.hook.filters.prod).toBe('4101');
    expect(new URLSearchParams(result.current.search).get('prod')).toBe('4101');
    act(() => result.current.hook.setFilters({ prod: '' }));
    expect(new URLSearchParams(result.current.search).has('prod')).toBe(false);
  });

  it('changing a filter closes the product panel and the selection; the page keeps both', () => {
    const { result } = setup('/?estado=active&prod=4101&sel=MLA1');
    act(() => result.current.hook.setFilters({ pagina: 2 }));
    let params = new URLSearchParams(result.current.search);
    expect([params.get('prod'), params.get('sel')]).toEqual(['4101', 'MLA1']);
    act(() => result.current.hook.setFilters({ estado: ['paused'] }));
    params = new URLSearchParams(result.current.search);
    expect(params.has('prod')).toBe(false);
    expect(params.has('sel')).toBe(false);
  });

  it('opening a product keeps the selection, and a filter change written with `prod` keeps it', () => {
    const { result } = setup('/?estado=active&sel=MLA1');
    act(() => result.current.hook.setFilters({ prod: '0' }));
    expect(new URLSearchParams(result.current.search).get('sel')).toBe('MLA1');
    act(() => result.current.hook.setFilters({ estado: ['paused'], prod: '0' }));
    const params = new URLSearchParams(result.current.search);
    expect(params.get('prod')).toBe('0');
    expect(params.has('sel')).toBe(false);
  });

  it('changing the page keeps the filters and the selection', () => {
    const { result } = setup('/?estado=active&sel=MLA1');
    act(() => result.current.hook.setFilters({ pagina: 2 }));
    const params = new URLSearchParams(result.current.search);
    expect(params.get('pagina')).toBe('2');
    expect(params.get('estado')).toBe('active');
    expect(params.get('sel')).toBe('MLA1');
  });

  it('sorting goes back to page 1 and keeps the rest', () => {
    const { result } = setup('/?pagina=3&estado=active');
    act(() => result.current.hook.setFilters({ orden: 'precio', dir: 'asc' }));
    const params = new URLSearchParams(result.current.search);
    expect(params.has('pagina')).toBe(false);
    expect(params.get('orden')).toBe('precio');
    expect(params.get('dir')).toBe('asc');
    expect(params.get('estado')).toBe('active');
  });

  it('changing the page size goes back to page 1 and survives a reload', () => {
    const { result } = setup('/?pagina=3&estado=active');
    act(() => result.current.hook.setFilters({ limite: 100 }));
    const params = new URLSearchParams(result.current.search);
    expect(params.get('limite')).toBe('100');
    expect(params.has('pagina')).toBe(false);
    expect(params.get('estado')).toBe('active');
  });

  it('reset clears every param', () => {
    const { result } = setup('/?q=a&estado=active&pagina=2');
    act(() => result.current.hook.resetFilters());
    expect(result.current.search).toBe('');
  });
});

describe('buildItemsParams', () => {
  const base = setup('/').result.current.hook.filters;

  it('sends only what is set, csv joined, with limit and offset', () => {
    const params = buildItemsParams({ ...base, q: ' router ', estado: ['active'], tipo: ['full', 'catalogo'], pagina: 3 });
    expect(params).toEqual({ q: 'router', estado: 'active', tipo: 'full,catalogo', limit: PAGE_SIZE, offset: 2 * PAGE_SIZE });
  });

  it('sends the backend vocabulary for "sin tienda"', () => {
    expect(buildItemsParams({ ...base, tiendas: ['57997', 'sin_tienda'] }).tiendas).toBe('57997,none');
  });

  it('maps the sort to orden/dir and never sends view-only params', () => {
    const params = buildItemsParams({ ...base, orden: 'titulo', dir: 'desc', vista: 'agrupado', sel: 'MLA1', tab: 'x' });
    expect(params).toMatchObject({ orden: 'titulo', dir: 'desc' });
    expect(params).not.toHaveProperty('vista');
    expect(params).not.toHaveProperty('sel');
    expect(params).not.toHaveProperty('tab');
    expect(params).not.toHaveProperty('pagina');
  });

  it('uses the page size of the URL', () => {
    expect(buildItemsParams({ ...base, limite: 100, pagina: 2 })).toMatchObject({ limit: 100, offset: 100 });
  });
});

describe('markup filters (publicaciones-ml-vista P11b.T2)', () => {
  const filtersOf = (url) => setup(url).result.current.hook.filters;
  const base = filtersOf('/');

  it('reads markup_neg, markup_min and markup_max from the URL', () => {
    expect(filtersOf('/?markup_neg=1&markup_min=-5&markup_max=20')).toMatchObject({
      markup_neg: '1',
      markup_min: '-5',
      markup_max: '20',
    });
    expect(base).toMatchObject({ markup_neg: '', markup_min: '', markup_max: '' });
  });

  it('reads `markup_neg` one way for the switch and the request: only 1 or true mean on', () => {
    expect(filtersOf('/?markup_neg=true').markup_neg).toBe('1');
    expect(filtersOf('/?markup_neg=1').markup_neg).toBe('1');
    for (const off of ['0', 'false', 'no', '']) expect(filtersOf(`/?markup_neg=${off}`).markup_neg).toBe('');
  });

  it('writes them to the URL, goes back to page 1 and drops them when emptied', () => {
    const { result } = setup('/?pagina=3');
    act(() => result.current.hook.setFilters({ markup_neg: '1', markup_min: '-5' }));
    const params = new URLSearchParams(result.current.search);
    expect(params.get('markup_neg')).toBe('1');
    expect(params.get('markup_min')).toBe('-5');
    expect(params.has('pagina')).toBe(false);
    act(() => result.current.hook.setFilters({ markup_neg: '', markup_min: '' }));
    expect(result.current.search).toBe('');
  });

  it('counts as an active filter and as a change of the filter set', () => {
    const { result } = setup('/');
    const before = result.current.hook.filterKey;
    act(() => result.current.hook.setFilters({ markup_max: '10' }));
    expect(result.current.hook.filterKey).not.toBe(before);
    expect(FILTER_KEYS).toEqual(expect.arrayContaining(['markup_neg', 'markup_min', 'markup_max']));
  });

  it('sends them only to a user with ver_ganancia: the backend answers 403 otherwise', () => {
    const filters = { ...base, markup_neg: '1', markup_min: '-5', markup_max: ' 20 ', orden: 'markup', dir: 'asc' };
    expect(buildItemsParams(filters, PAGE_SIZE, { canSeeMargin: true })).toMatchObject({
      markup_neg: true,
      markup_min: '-5',
      markup_max: '20',
      orden: 'markup',
      dir: 'asc',
    });
    const without = buildItemsParams(filters, PAGE_SIZE);
    expect(without).not.toHaveProperty('markup_neg');
    expect(without).not.toHaveProperty('markup_min');
    expect(without).not.toHaveProperty('markup_max');
    // A link shared by someone with the permission must not break the list for someone without it.
    expect(without).not.toHaveProperty('orden');
    expect(without).not.toHaveProperty('dir');
  });

  it('accepts a decimal comma and omits a blank bound', () => {
    const params = buildItemsParams({ ...base, markup_min: '-2,5', markup_max: '  ' }, PAGE_SIZE, { canSeeMargin: true });
    expect(params.markup_min).toBe('-2.5');
    expect(params).not.toHaveProperty('markup_max');
  });
});

describe('the tree dimension (`agrupar`)', () => {
  it('defaults to marca', () => {
    expect(setup('/').result.current.hook.filters.agrupar).toBe('marca');
  });

  it('reads a dimension the tree is grouped by', () => {
    expect(setup('/?agrupar=categoria').result.current.hook.filters.agrupar).toBe('categoria');
    expect(setup('/?agrupar=subcategoria').result.current.hook.filters.agrupar).toBe('subcategoria');
    expect(setup('/?agrupar=tienda').result.current.hook.filters.agrupar).toBe('tienda');
    expect(setup('/?agrupar=pm').result.current.hook.filters.agrupar).toBe('pm');
  });

  it("offers exactly Métricas ML's dimensions, in Métricas' order", () => {
    expect(AGRUPAR_DIMENSIONS).toEqual(DIMENSION_OPTIONS.map((option) => option.value));
  });

  it('falls back to marca on a dimension the tree is not grouped by', () => {
    expect(setup('/?agrupar=otra').result.current.hook.filters.agrupar).toBe('marca');
    expect(setup('/?agrupar=producto').result.current.hook.filters.agrupar).toBe('marca');
  });

  it('is not a filter: never sent to /items, and "Limpiar filtros" keeps it', () => {
    const { result } = setup('/?vista=agrupado&agrupar=categoria&estado=active');
    expect(buildItemsParams(result.current.hook.filters)).not.toHaveProperty('agrupar');
    expect(FILTER_KEYS).not.toContain('agrupar');
    act(() => result.current.hook.resetFilters());
    expect(new URLSearchParams(result.current.search).get('agrupar')).toBe('categoria');
  });

  it('changing it closes the selection, like the view', () => {
    const { result } = setup('/?vista=agrupado&sel=MLA1&tab=eventos');
    act(() => result.current.hook.setFilters({ agrupar: 'subcategoria' }));
    const params = new URLSearchParams(result.current.search);
    expect(params.get('agrupar')).toBe('subcategoria');
    expect(params.has('sel')).toBe(false);
  });
});

describe('sorting by Métricas ML figures', () => {
  const base = setup('/').result.current.hook.filters;
  const SALES = { canSeeSales: true };
  const ALL = { canSeeSales: true, canSeeMargin: true };

  it('defaults to Facturado 30D, highest first, for a user who sees the sales -- as Métricas does', () => {
    expect(effectiveSort(base, SALES)).toEqual({ key: 'facturado_30d', dir: 'desc' });
    // The direction is explicit too: the request says what the header shows, not the backend's default.
    expect(buildItemsParams(base, PAGE_SIZE, SALES)).toMatchObject({ orden: 'facturado_30d', dir: 'desc' });
  });

  it('keeps the activity default (no orden sent) for a user who does not see the sales', () => {
    expect(effectiveSort(base, {})).toEqual({ key: 'actividad', dir: 'desc' });
    expect(buildItemsParams(base)).not.toHaveProperty('orden');
  });

  it('sends a Métricas sort only to who may ask for it: a shared link falls back on the default', () => {
    const units = { ...base, orden: 'unidades_7d', dir: 'asc' };
    expect(buildItemsParams(units, PAGE_SIZE, SALES)).toMatchObject({ orden: 'unidades_7d', dir: 'asc' });
    expect(buildItemsParams(units)).not.toHaveProperty('orden');
    expect(buildItemsParams(units)).not.toHaveProperty('dir');
    for (const orden of ['markup_30d', 'total_gauss_30d']) {
      const margin = { ...base, orden, dir: 'asc' };
      expect(buildItemsParams(margin, PAGE_SIZE, ALL)).toMatchObject({ orden, dir: 'asc' });
      // The link's own `dir` belongs to the sort it named: the default goes with its own direction.
      expect(buildItemsParams(margin, PAGE_SIZE, SALES)).toMatchObject({ orden: 'facturado_30d', dir: 'desc' });
      expect(effectiveSort(margin, SALES)).toEqual({ key: 'facturado_30d', dir: 'desc' });
    }
  });

  it('a column sort stays what it was for everyone', () => {
    expect(buildItemsParams({ ...base, orden: 'precio', dir: 'asc' }, PAGE_SIZE, SALES)).toMatchObject({ orden: 'precio', dir: 'asc' });
    expect(effectiveSort({ ...base, orden: 'precio' }, SALES)).toEqual({ key: 'precio', dir: 'asc' });
  });
});

describe('the legacy stock chip value', () => {
  // `sin_stock` (ML's available, a sum) was the old "Sin stock ML" chip; the chips are now one per stock column.
  it('reads an old link\'s `sin_stock` as "Sin stock propio", so its chip shows active', () => {
    expect(setup('/?stock=sin_stock,erp_sin_stock').result.current.hook.filters.stock).toEqual(['propio_sin_stock', 'erp_sin_stock']);
  });

  it('never repeats a value an old link also carried in the new form', () => {
    expect(setup('/?stock=propio_sin_stock,sin_stock').result.current.hook.filters.stock).toEqual(['propio_sin_stock']);
  });

  it('sends the new value to /items', () => {
    const filters = setup('/?stock=sin_stock').result.current.hook.filters;
    expect(buildItemsParams(filters).stock).toBe('propio_sin_stock');
  });
});

describe('the Producto view (vista=producto)', () => {
  const base = setup('/').result.current.hook.filters;
  const sales = { canSeeSales: true, canSeeMargin: false };

  it('reads vista=producto from the URL and keeps it through "Limpiar filtros"', () => {
    const { result } = setup('/?vista=producto&estado=active');
    expect(result.current.hook.filters.vista).toBe('producto');
    act(() => result.current.hook.resetFilters());
    expect(result.current.search).toBe('?vista=producto');
  });

  it('sorts by Facturado 30D for who sees the sales, by name otherwise', () => {
    expect(effectiveProductSort(base, sales)).toEqual({ key: 'facturado_30d', dir: 'desc' });
    expect(effectiveProductSort(base, {})).toEqual({ key: 'titulo', dir: 'asc' });
  });

  it("keeps the URL's sort only when the products can be sorted by it and the user may ask for it", () => {
    expect(effectiveProductSort({ ...base, orden: 'unidades_7d', dir: 'asc' }, sales)).toEqual({ key: 'unidades_7d', dir: 'asc' });
    // A sort of the publication list the products have no figure for.
    expect(effectiveProductSort({ ...base, orden: 'precio', dir: 'asc' }, sales)).toEqual({ key: 'facturado_30d', dir: 'desc' });
    // A margin sort without the margin permission.
    expect(effectiveProductSort({ ...base, orden: 'markup_30d' }, sales)).toEqual({ key: 'facturado_30d', dir: 'desc' });
    expect(effectiveProductSort({ ...base, orden: 'markup_30d' }, { canSeeSales: true, canSeeMargin: true })).toEqual({
      key: 'markup_30d',
      dir: 'desc',
    });
  });

  it('asks /products with the filters, the effective sort and the page, never the markup filters', () => {
    const filters = { ...base, estado: ['active'], markup_neg: '1', markup_min: '5', orden: 'precio', pagina: 2 };
    expect(buildProductsParams(filters, 25, sales)).toEqual({
      estado: 'active',
      orden: 'facturado_30d',
      dir: 'desc',
      limit: 25,
      offset: 25,
    });
  });
});

describe("Productos' presence filters (S5)", () => {
  const base = setup('/').result.current.hook.filters;

  it("keeps Productos' URL keys and values", () => {
    expect(PRESENCE_VALUES).toEqual({
      rebate: ['con_rebate', 'sin_rebate'],
      oferta: ['con_oferta', 'sin_oferta'],
      webtransf: ['con_web_transf', 'sin_web_transf'],
      tiendanube: ['con_descuento', 'sin_descuento', 'no_publicado'],
      outofcards: ['con_out_of_cards', 'sin_out_of_cards'],
      precio: ['con_precio', 'sin_precio'],
      nuevos: ['ultimos_7_dias'],
    });
    expect(FILTER_KEYS).toEqual(expect.arrayContaining(Object.keys(PRESENCE_VALUES)));
  });

  it('reads them from the URL and drops a value outside the vocabulary', () => {
    const f = setup('/?rebate=sin_rebate&tiendanube=no_publicado&outofcards=quizas').result.current.hook.filters;
    expect([f.rebate, f.tiendanube, f.outofcards, f.oferta, f.webtransf]).toEqual(['sin_rebate', 'no_publicado', '', '', '']);
  });

  it('a change goes back to page 1 and counts as a change of the filter set; reset clears it', () => {
    const { result } = setup('/?pagina=3&sel=MLA1');
    const before = result.current.hook.filterKey;
    act(() => result.current.hook.setFilters({ webtransf: 'con_web_transf' }));
    expect(result.current.search).toBe('?webtransf=con_web_transf');
    expect(result.current.hook.filterKey).not.toBe(before);
    act(() => result.current.hook.resetFilters());
    expect(result.current.search).toBe('');
  });

  it('sends the params GET /productos takes', () => {
    const filters = {
      ...base,
      rebate: 'con_rebate',
      oferta: 'sin_oferta',
      webtransf: 'sin_web_transf',
      tiendanube: 'sin_descuento',
      outofcards: 'con_out_of_cards',
    };
    const presence = {
      con_rebate: true,
      con_oferta: false,
      con_web_transf: false,
      tn_sin_descuento: true,
      out_of_cards: true,
    };
    expect(buildItemsParams(filters, 50)).toEqual({ ...presence, limit: 50, offset: 0 });
    expect(buildProductsParams(filters, 50)).toMatchObject(presence);
    expect(buildKpiParams(filters, '30d')).toEqual({ ...presence, periodo: '30d' });
    expect(buildItemsParams({ ...base, tiendanube: 'con_descuento' }, 50).tn_con_descuento).toBe(true);
    expect(buildItemsParams({ ...base, tiendanube: 'no_publicado' }, 50).tn_no_publicado).toBe(true);
  });

  it("sends Productos' precio and nuevos params (P6)", () => {
    expect(buildItemsParams({ ...base, precio: 'con_precio', nuevos: 'ultimos_7_dias' }, 50)).toEqual({
      con_precio: true,
      nuevos_ultimos_7_dias: true,
      limit: 50,
      offset: 0,
    });
    expect(buildItemsParams({ ...base, precio: 'sin_precio' }, 50).con_precio).toBe(false);
    expect(buildProductIdsParams({ ...base, precio: 'sin_precio' }).con_precio).toBe(false);
  });

  it('in the Producto view, the KPI strip asks mejor oferta of the product, as the product rows do', () => {
    const oferta = { ...base, oferta: 'sin_oferta' };
    expect(buildKpiParams({ ...oferta, vista: 'producto' }, '30d')).toEqual({
      con_oferta: false,
      oferta_por_producto: true,
      periodo: '30d',
    });
    expect(buildKpiParams(oferta, '30d')).toEqual({ con_oferta: false, periodo: '30d' });
    expect(buildKpiParams({ ...base, vista: 'producto', rebate: 'con_rebate' }, '30d')).toEqual({
      con_rebate: true,
      periodo: '30d',
    });
  });
});

describe("Productos' markup sign filters (P6b)", () => {
  const url = '/?mkclasica=positivo&mkrebate=negativo&mkoferta=quizas';

  it("reads Productos' URL keys only for a user who may see margins", () => {
    const f = setup(url, { canSeeMargin: true }).result.current.hook.filters;
    expect([f.mkclasica, f.mkrebate, f.mkoferta, f.mkwebtransf]).toEqual(['positivo', 'negativo', '', '']);
    const hidden = setup(url).result.current.hook.filters;
    expect([hidden.mkclasica, hidden.mkrebate]).toEqual(['', '']); // a shared link never asks a 403
  });

  it('sends the params GET /productos takes, to every view: they are a filter of the query, not of the page', () => {
    const f = setup(url, { canSeeMargin: true }).result.current.hook.filters;
    const signs = { markup_clasica_positivo: true, markup_rebate_positivo: false };
    expect(buildItemsParams(f, 50)).toMatchObject(signs);
    expect(buildProductsParams(f, 50)).toMatchObject(signs);
    expect(buildKpiParams(f, '30d')).toMatchObject(signs);
    expect(buildProductIdsParams(f)).toMatchObject(signs);
    expect(hasMarkupFilter(f)).toBe(false); // the KPI strip applies them too
  });
});

describe("Productos' audit filter (P6c)", () => {
  it("reads Productos' URL keys and sends GET /productos' params, to every view", () => {
    const { result } = setup('/?audit_usuarios=5,6&audit_tipos=activar_rebate&audit_desde=2026-10-20T09:00&audit_hasta=2026-10-21');
    const f = result.current.hook.filters;
    expect([f.audit_usuarios, f.audit_tipos, f.audit_desde, f.audit_hasta]).toEqual([
      ['5', '6'],
      ['activar_rebate'],
      '2026-10-20T09:00',
      '2026-10-21',
    ]);
    const audit = {
      audit_usuarios: '5,6',
      audit_tipos_accion: 'activar_rebate',
      audit_fecha_desde: '2026-10-20T09:00',
      audit_fecha_hasta: '2026-10-21',
    };
    expect(buildItemsParams(f, 50)).toEqual({ ...audit, limit: 50, offset: 0 });
    expect(buildKpiParams(f, '30d')).toMatchObject(audit);
    expect(buildProductIdsParams(f)).toMatchObject(audit);
    expect(FILTER_KEYS).toEqual(expect.arrayContaining(['audit_usuarios', 'audit_tipos', 'audit_desde', 'audit_hasta']));
  });
});

describe("Productos' promo and wholesale filters (P6d)", () => {
  it("reads Productos' URL keys and drops values outside the vocabulary", () => {
    const f = setup('/?promo_tipos=DEAL,REGALO&promo_estado=aplicada&pxq=con_pxq').result.current.hook.filters;
    expect([f.promo_tipos, f.promo_estado, f.pxq]).toEqual([['DEAL'], 'aplicada', 'con_pxq']);
    const bad = setup('/?promo_estado=x&pxq=sin').result.current.hook.filters;
    expect([bad.promo_estado, bad.pxq]).toEqual(['', '']);
  });

  it('sends what GET /productos takes: types with their state, else the legacy booleans, and con_pxq', () => {
    const base = setup('/').result.current.hook.filters;
    expect(buildItemsParams({ ...base, promo_tipos: ['DEAL', 'SMART'], promo_estado: '' }, 50)).toEqual({
      promo_tipos: 'DEAL,SMART',
      promo_estado: 'disponible',
      limit: 50,
      offset: 0,
    });
    expect(buildItemsParams({ ...base, promo_estado: 'aplicada' }, 50).con_promo_aplicada).toBe(true);
    expect(buildItemsParams({ ...base, promo_estado: 'sin_aplicar' }, 50).con_promo_sin_aplicar).toBe(true);
    expect(buildKpiParams({ ...base, pxq: 'con_pxq' }, '30d')).toEqual({ con_pxq: true, periodo: '30d' });
    expect(FILTER_KEYS).toEqual(expect.arrayContaining(['promo_tipos', 'promo_estado', 'pxq']));
  });
});

describe('buildProductIdsParams (the products a bulk action acts on)', () => {
  const base = setup('/').result.current.hook.filters;

  it('sends the list filters and nothing that pages or sorts', () => {
    const filters = { ...base, q: 'router', estado: ['active'], marcas: ['TP-LINK'], pagina: 3, orden: 'precio', dir: 'asc' };
    expect(buildProductIdsParams(filters)).toEqual({ q: 'router', estado: 'active', marcas: 'TP-LINK' });
  });

  it('leaves the markup filters to the caller, which sends them only where the list applies them', () => {
    expect(buildProductIdsParams({ ...base, markup_neg: '1', markup_min: '5' })).toEqual({});
  });

  it('asks mejor oferta of the product in the Producto view only, as its rows do', () => {
    const oferta = { ...base, oferta: 'sin_oferta' };
    expect(buildProductIdsParams({ ...oferta, vista: 'producto' })).toEqual({ con_oferta: false, oferta_por_producto: true });
    expect(buildProductIdsParams(oferta)).toEqual({ con_oferta: false });
  });
});

describe('the color layer (`equipo`, S8)', () => {
  const base = setup('/').result.current.hook.filters;

  it('reads the team from the URL, the global layer (empty) by default', () => {
    expect(base.equipo).toBe('');
    expect(setup('/?equipo=12').result.current.hook.filters.equipo).toBe('12');
  });

  it('asks the rows of every view on that layer', () => {
    expect(buildItemsParams({ ...base, equipo: '12' })).toMatchObject({ equipo_id: '12' });
    expect(buildProductsParams({ ...base, equipo: '12' })).toMatchObject({ equipo_id: '12' });
    expect(buildItemsParams(base)).not.toHaveProperty('equipo_id');
  });

  it('never sends it where colors are not shown: the KPI strip, the bulk set and the CSV export', () => {
    expect(buildKpiParams({ ...base, equipo: '12' }, '30d')).toEqual({ periodo: '30d' });
    expect(buildProductIdsParams({ ...base, equipo: '12' })).toEqual({});
    expect(buildExportParams({ ...base, equipo: '12' })).not.toHaveProperty('equipo_id');
    expect(buildExportParams({ ...base, vista: 'producto', equipo: '12' })).not.toHaveProperty('equipo_id');
  });

  it('is how the rows are looked at, not a filter: "Limpiar filtros" keeps it and it never resets the page', () => {
    const { result } = setup('/?equipo=12&estado=active&pagina=2');
    expect(FILTER_KEYS).not.toContain('equipo');
    act(() => result.current.hook.setFilters({ equipo: '3' }));
    expect(new URLSearchParams(result.current.search).get('pagina')).toBe('2');
    act(() => result.current.hook.resetFilters());
    expect(result.current.search).toBe('?equipo=3');
  });
});

describe("the color filter (`colores`, P6): Productos' colors on the layer on show", () => {
  const base = setup('/').result.current.hook.filters;

  it('reads the colors from the URL, Productos\' values and `sin_color`, dropping unknown ones', () => {
    expect(base.colores).toEqual([]);
    expect(setup('/?colores=rojo,sin_color,fucsia').result.current.hook.filters.colores).toEqual(['rojo', 'sin_color']);
  });

  it('is a filter: every list asks it, a change goes back to page 1 and "Limpiar filtros" clears it', () => {
    expect(buildItemsParams({ ...base, colores: ['rojo', 'sin_color'] })).toMatchObject({ colores: 'rojo,sin_color' });
    expect(buildProductsParams({ ...base, colores: ['azul'] })).toMatchObject({ colores: 'azul' });
    const { result } = setup('/?pagina=3&equipo=12');
    act(() => result.current.hook.setFilters({ colores: ['verde'] }));
    expect(new URLSearchParams(result.current.search).get('pagina')).toBeNull();
    act(() => result.current.hook.resetFilters());
    expect(result.current.search).toBe('?equipo=12');
  });

  it('takes the layer wherever it goes: the strip, the bulk set and the export count the same products', () => {
    const colored = { ...base, colores: ['verde'], equipo: '12' };
    expect(buildKpiParams(colored, '30d')).toEqual({ colores: 'verde', equipo_id: '12', periodo: '30d' });
    expect(buildProductIdsParams(colored)).toEqual({ colores: 'verde', equipo_id: '12' });
    expect(buildExportParams(colored)).toMatchObject({ colores: 'verde', equipo_id: '12' });
  });

  it('with a color filter on, another layer is another set: the filter key changes', () => {
    const { result } = setup('/?colores=verde');
    const before = result.current.hook.filterKey;
    act(() => result.current.hook.setFilters({ equipo: '12' }));
    expect(result.current.hook.filterKey).not.toBe(before);
    const plain = setup('/');
    const plainBefore = plain.result.current.hook.filterKey;
    act(() => plain.result.current.hook.setFilters({ equipo: '12' }));
    expect(plain.result.current.hook.filterKey).toBe(plainBefore);
  });
});

describe("the price columns' mode (`modo`, S11): Productos' Normal / Cuotas / PVP", () => {
  it('reads the mode from the URL, Normal by default and for an unknown value', () => {
    expect(PRICE_MODES).toEqual(['normal', 'cuotas', 'pvp']);
    expect(setup('/').result.current.hook.filters.modo).toBe('normal');
    expect(setup('/?modo=pvp').result.current.hook.filters.modo).toBe('pvp');
    expect(setup('/?modo=otro').result.current.hook.filters.modo).toBe('normal');
  });

  it('is how the rows are looked at, not a filter: it never reaches the backend, resets no page and survives "Limpiar filtros"', () => {
    const { result } = setup('/?modo=cuotas&estado=active&pagina=2');
    expect(FILTER_KEYS).not.toContain('modo');
    expect(buildItemsParams(result.current.hook.filters)).not.toHaveProperty('modo');
    act(() => result.current.hook.setFilters({ modo: 'pvp' }));
    expect(new URLSearchParams(result.current.search).get('pagina')).toBe('2');
    act(() => result.current.hook.resetFilters());
    expect(result.current.search).toBe('?modo=pvp');
  });
});

describe("Productos' Sin MLA (mla=sin_mla, Producto view only)", () => {
  const producto = { ...setup('/?vista=producto').result.current.hook.filters, mla: 'sin_mla' };
  const sales = { canSeeSales: true, canSeeMargin: false };

  it('reads mla=sin_mla only in the Producto view', () => {
    expect(setup('/?vista=producto&mla=sin_mla').result.current.hook.filters.mla).toBe('sin_mla');
    expect(setup('/?mla=sin_mla').result.current.hook.filters.mla).toBe('');
    expect(setup('/?vista=producto&mla=otro').result.current.hook.filters.mla).toBe('');
  });

  it('is a filter: "Limpiar filtros" clears it and it resets the page', () => {
    const { result } = setup('/?vista=producto&mla=sin_mla&pagina=3');
    act(() => result.current.hook.resetFilters());
    expect(result.current.search).toBe('?vista=producto');
    expect(FILTER_KEYS).toContain('mla');
  });

  it('asks /products, its export and the bulk set for the products without MLA, sorted by name', () => {
    expect(buildProductsParams(producto, 25, sales)).toEqual({ con_mla: false, orden: 'titulo', dir: 'asc', limit: 25, offset: 0 });
    expect(buildExportParams(producto, sales)).toEqual({ con_mla: false, orden: 'titulo', dir: 'asc' });
    expect(buildProductIdsParams(producto)).toEqual({ con_mla: false });
    expect(effectiveProductSort({ ...producto, orden: 'titulo', dir: 'desc' }, sales)).toEqual({ key: 'titulo', dir: 'desc' });
  });

  it('never reaches the KPI strip, which counts publications', () => {
    expect(buildKpiParams(producto, '30d')).toEqual({ periodo: '30d' });
  });

  it('turning it on clears the filters only a publication has', () => {
    const { result } = setup(
      '/?vista=producto&estado=active&marcas=TP-Link&tiendas=57997&oferta=con_oferta&familia=9&stock=full_sin_stock,erp_con_stock',
    );
    act(() => result.current.hook.setFilters(sinMlaUpdates(result.current.hook.filters)));
    expect(result.current.search).toBe('?vista=producto&marcas=TP-Link&stock=erp_con_stock&mla=sin_mla');
  });
});

describe('sorting by several columns (S12e, Shift+click like Productos)', () => {
  const base = setup('/').result.current.hook.filters;
  const SALES = { canSeeSales: true };
  const ALL = { canSeeSales: true, canSeeMargin: true };

  it('reads orden and dir as csv, one direction per key', () => {
    const { result } = setup('/?orden=marca,precio&dir=asc,desc');
    expect(result.current.hook.filters).toMatchObject({ orden: 'marca,precio', dir: 'asc,desc' });
    expect(setup('/?orden=marca,precio&dir=asc,sideways').result.current.hook.filters.dir).toBe('asc,');
    expect(setup('/?orden=precio&dir=sideways').result.current.hook.filters.dir).toBe('');
  });

  it('asks /items for every key the user may ask for, in order', () => {
    const filters = { ...base, orden: 'marca,precio', dir: 'asc,desc' };
    expect(buildItemsParams(filters, 50, ALL)).toMatchObject({ orden: 'marca,precio', dir: 'asc,desc' });
    expect(effectiveSortKeys(filters, ALL)).toEqual([
      { key: 'marca', dir: 'asc' },
      { key: 'precio', dir: 'desc' },
    ]);
    // A missing direction is the key's default; a key the user may not ask for is left out.
    expect(effectiveSortKeys({ ...base, orden: 'precio,costo,titulo', dir: '' }, SALES)).toEqual([
      { key: 'precio', dir: 'asc' },
      { key: 'titulo', dir: 'asc' },
    ]);
  });

  it('keeps the markup and the Métricas figures only as the first key of the publications list', () => {
    expect(effectiveSortKeys({ ...base, orden: 'precio,markup,facturado_30d', dir: '' }, ALL)).toEqual([
      { key: 'precio', dir: 'asc' },
    ]);
    expect(effectiveSortKeys({ ...base, orden: 'facturado_30d,precio', dir: 'desc,asc' }, ALL)).toEqual([
      { key: 'facturado_30d', dir: 'desc' },
      { key: 'precio', dir: 'asc' },
    ]);
  });

  it('combines every figure in the Producto view, and asks /products for all of them', () => {
    const filters = { ...base, vista: 'producto', orden: 'unidades_7d,titulo', dir: 'desc,desc' };
    expect(effectiveProductSortKeys(filters, SALES)).toEqual([
      { key: 'unidades_7d', dir: 'desc' },
      { key: 'titulo', dir: 'desc' },
    ]);
    expect(buildProductsParams(filters, 50, SALES)).toMatchObject({ orden: 'unidades_7d,titulo', dir: 'desc,desc' });
  });

  it('sorts the Sin MLA products by name alone, in the direction asked for it', () => {
    const filters = { ...base, vista: 'producto', mla: 'sin_mla', orden: 'facturado_30d,titulo', dir: 'desc,desc' };
    expect(effectiveProductSortKeys(filters, SALES)).toEqual([{ key: 'titulo', dir: 'desc' }]);
  });

  describe('nextSort (what a header click asks)', () => {
    const precio = [{ key: 'precio', dir: 'asc' }];

    it('a plain click sorts by that column alone: its default first, then the other way', () => {
      expect(nextSort(precio, 'marca')).toEqual([{ key: 'marca', dir: 'asc' }]);
      expect(nextSort(precio, 'precio')).toEqual([{ key: 'precio', dir: 'desc' }]);
      expect(nextSort([...precio, { key: 'marca', dir: 'asc' }], 'marca')).toEqual([{ key: 'marca', dir: 'asc' }]);
    });

    it('Shift+click adds the column, flips it, then takes it out', () => {
      const added = nextSort(precio, 'stock_propio', { shift: true });
      expect(added).toEqual([...precio, { key: 'stock_propio', dir: 'desc' }]);
      const flipped = nextSort(added, 'stock_propio', { shift: true });
      expect(flipped).toEqual([...precio, { key: 'stock_propio', dir: 'asc' }]);
      expect(nextSort(flipped, 'stock_propio', { shift: true })).toEqual(precio);
      expect(nextSort(precio, 'precio', { shift: true })).toEqual([{ key: 'precio', dir: 'desc' }]);
      expect(nextSort([{ key: 'precio', dir: 'desc' }], 'precio', { shift: true })).toEqual([]);
    });

    it('Shift+click on a key that only leads (or over one) replaces the sort', () => {
      const leadOnly = (key) => key === 'markup' || key === 'facturado_30d';
      expect(nextSort(precio, 'facturado_30d', { shift: true, leadOnly })).toEqual([{ key: 'facturado_30d', dir: 'desc' }]);
      expect(nextSort([{ key: 'facturado_30d', dir: 'desc' }], 'precio', { shift: true, leadOnly })).toEqual(precio);
    });
  });
});
