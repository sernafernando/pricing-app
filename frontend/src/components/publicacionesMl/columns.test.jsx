/**
 * The columns of the Publicaciones ML table, grouped like Métricas ML's board
 * (owner-approved layout): Publicación (with store and link inside), Estado,
 * Precio, then VENTAS, MARKUP, RESULTADO, ROTACIÓN -- Métricas' own figures --
 * and STOCK as three separate figures, never summed. Vínculo, Tienda, Última
 * actividad and Último evento start hidden (the picker brings them back).
 */
import { describe, it, expect } from 'vitest';
import { COLUMN_GROUPS } from '../metricasMl/metricasMlColumns';
import { DEFAULT_DIRECTION } from '../../hooks/usePublicacionesMLFilters';
import { buildColumns, columnChoicesOver, defaultColumnVisibility } from './columns';

const groupLabel = (id) => COLUMN_GROUPS.find((group) => group.id === id).label;
const keys = (options) => buildColumns({ eventsEnabled: false, ...options }).map((column) => column.key);
const byKey = (options) => Object.fromEntries(buildColumns({ eventsEnabled: true, ...options }).map((column) => [column.key, column]));

const ALL = [
  'titulo',
  'estado',
  'precio',
  'unidades_7d',
  'unidades_30d',
  'units_trend',
  'markup',
  'markup_30d',
  'markup_trend',
  'facturado_30d',
  'total_gauss_30d',
  'last_sale',
  'ageing',
  'stock_propio',
  'stock_full',
  'stock_erp',
  'vinculo',
  'tienda',
  'actividad',
];

describe('layout', () => {
  it('orders the groups like Métricas, the stock last, the hidden extras at the end', () => {
    expect(keys({ canSeeSales: true, canSeeMargin: true })).toEqual(ALL);
    expect(keys({ canSeeSales: true, canSeeMargin: true, eventsEnabled: true })).toEqual([...ALL, 'evento']);
  });

  it('groups the figures under Métricas’ own group names, and leaves Publicación, Estado and Precio ungrouped', () => {
    const columns = byKey({ canSeeSales: true, canSeeMargin: true });
    expect(['titulo', 'estado', 'precio', 'vinculo', 'tienda', 'actividad', 'evento'].map((key) => columns[key].group)).toEqual(
      Array(7).fill(undefined),
    );
    expect(['unidades_7d', 'unidades_30d', 'units_trend'].map((key) => columns[key].group)).toEqual(Array(3).fill(groupLabel('ventas')));
    expect(['markup', 'markup_30d', 'markup_trend'].map((key) => columns[key].group)).toEqual(Array(3).fill(groupLabel('markup')));
    expect(['facturado_30d', 'total_gauss_30d'].map((key) => columns[key].group)).toEqual(Array(2).fill(groupLabel('resultado')));
    expect(['last_sale', 'ageing'].map((key) => columns[key].group)).toEqual(Array(2).fill(groupLabel('rotacion')));
    expect(['stock_propio', 'stock_full', 'stock_erp'].map((key) => columns[key].group)).toEqual(Array(3).fill('Stock'));
  });

  it('names the leaves as owner-approved, and gives the picker names that stand alone', () => {
    const columns = byKey({ canSeeSales: true, canSeeMargin: true });
    const headers = (list) => list.map((key) => columns[key].header);
    expect(headers(['unidades_7d', 'unidades_30d', 'units_trend'])).toEqual(['7D', '30D', 'Tendencia']);
    expect(headers(['markup', 'markup_30d', 'markup_trend'])).toEqual(['Actual', 'Real 30D', 'Tendencia']);
    expect(headers(['facturado_30d', 'total_gauss_30d', 'last_sale', 'ageing'])).toEqual(['Facturado 30D', 'Total Gauss 30D', 'Última venta', 'Ageing']);
    expect(headers(['stock_propio', 'stock_full', 'stock_erp'])).toEqual(['Propio', 'Full', 'ERP']);
    const labels = (list) => list.map((key) => columns[key].label);
    expect(labels(['units_trend', 'markup', 'markup_trend', 'stock_propio', 'stock_full', 'stock_erp'])).toEqual([
      'Tendencia de ventas',
      'Markup actual',
      'Tendencia de markup',
      'Stock propio',
      'Stock Full',
      'Stock ERP',
    ]);
  });

  it('sorts what /items sorts: Métricas’ figures over the whole set, the current markup, each stock on its own', () => {
    const sortable = buildColumns({ eventsEnabled: true, canSeeSales: true, canSeeMargin: true })
      .filter((column) => column.sortable)
      .map((column) => column.key);
    expect(sortable).toEqual([
      'titulo',
      'precio',
      'unidades_7d',
      'unidades_30d',
      'markup',
      'markup_30d',
      'facturado_30d',
      'total_gauss_30d',
      'stock_propio',
      'stock_full',
      'stock_erp',
      'actividad',
    ]);
    expect(DEFAULT_DIRECTION.stock_propio).toBe('desc');
    for (const key of ['unidades_7d', 'unidades_30d', 'markup_30d', 'facturado_30d', 'total_gauss_30d']) {
      expect(DEFAULT_DIRECTION[key]).toBe('desc');
    }
  });
});

describe('SKU divergence', () => {
  it('the "SKU distinto" column exists only while the divergence filter is on, right after Publicación', () => {
    expect(keys({})).not.toContain('sku_divergencia');
    const got = keys({ skuDivergence: true });
    expect(got.slice(0, 2)).toEqual(['titulo', 'sku_divergencia']);
    expect(byKey({ skuDivergence: true }).sku_divergencia.header).toBe('SKU distinto');
  });
});

describe('permissions', () => {
  it('without ml_metricas.ver there are no Métricas figures; the current markup needs only ver_ganancia', () => {
    expect(keys({ canSeeMargin: true })).toEqual(['titulo', 'estado', 'precio', 'markup', 'stock_propio', 'stock_full', 'stock_erp', 'vinculo', 'tienda', 'actividad']);
    expect(keys({})).toEqual(['titulo', 'estado', 'precio', 'stock_propio', 'stock_full', 'stock_erp', 'vinculo', 'tienda', 'actividad']);
  });

  it('with ml_metricas.ver but no ver_ganancia: units, gross and rotation, no markup and no Total Gauss', () => {
    const got = keys({ canSeeSales: true });
    expect(got).toEqual(expect.arrayContaining(['unidades_7d', 'unidades_30d', 'units_trend', 'facturado_30d', 'last_sale', 'ageing']));
    expect(got).not.toEqual(expect.arrayContaining(['markup']));
    for (const key of ['markup', 'markup_30d', 'markup_trend', 'total_gauss_30d']) expect(got).not.toContain(key);
  });
});

describe('the tree', () => {
  it('keeps the node figures right after Publicación, ungrouped', () => {
    const got = buildColumns({ eventsEnabled: false, canSeeSales: true, canSeeMargin: true, agrupado: true });
    expect(got.slice(0, 5).map((column) => [column.key, column.group])).toEqual([
      ['titulo', undefined],
      ['publicaciones', undefined],
      ['negativos', undefined],
      ['estado', undefined],
      ['precio', undefined],
    ]);
  });
});

describe('default visibility', () => {
  it('hides Vínculo, Tienda, Última actividad and Último evento: they live in the Publicación cell and the panel', () => {
    expect(defaultColumnVisibility()).toEqual({ vinculo: false, tienda: false, actividad: false, evento: false });
  });

  it('keeps only the user’s own picks apart from the defaults', () => {
    const defaults = defaultColumnVisibility();
    expect(columnChoicesOver({ ...defaults, tienda: true, stock_full: false }, defaults)).toEqual({ tienda: true, stock_full: false });
  });
});
