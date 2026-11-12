/**
 * The columns of the Publicaciones ML table, grouped like Métricas ML's board
 * (owner-approved layout): Publicación (with store and link inside), Estado,
 * Precio, then VENTAS, MARKUP, RESULTADO, ROTACIÓN -- Métricas' own figures --
 * and STOCK as three separate figures, never summed. Vínculo, Tienda, Última
 * actividad and Último evento start hidden (the picker brings them back).
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { COLUMN_GROUPS } from '../metricasMl/metricasMlColumns';
import { DEFAULT_DIRECTION } from '../../hooks/usePublicacionesMLFilters';
import { buildColumns, columnChoicesOver, defaultColumnVisibility } from './columns';

const groupLabel = (id) => COLUMN_GROUPS.find((group) => group.id === id).label;
const keys = (options) => buildColumns({ eventsEnabled: false, ...options }).map((column) => column.key);
const byKey = (options) => Object.fromEntries(buildColumns({ eventsEnabled: true, ...options }).map((column) => [column.key, column]));

const ALL = [
  'titulo',
  'tipo',
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
  'stock_erp',
  'stock_full',
  'stock_total',
  'codigo',
  'marca',
  'costo',
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
    expect(['titulo', 'tipo', 'estado', 'precio', 'vinculo', 'tienda', 'actividad', 'evento'].map((key) => columns[key].group)).toEqual(
      Array(8).fill(undefined),
    );
    expect(['unidades_7d', 'unidades_30d', 'units_trend'].map((key) => columns[key].group)).toEqual(Array(3).fill(groupLabel('ventas')));
    expect(['markup', 'markup_30d', 'markup_trend'].map((key) => columns[key].group)).toEqual(Array(3).fill(groupLabel('markup')));
    expect(['facturado_30d', 'total_gauss_30d'].map((key) => columns[key].group)).toEqual(Array(2).fill(groupLabel('resultado')));
    expect(['last_sale', 'ageing'].map((key) => columns[key].group)).toEqual(Array(2).fill(groupLabel('rotacion')));
    expect(['stock_erp', 'stock_full', 'stock_total'].map((key) => columns[key].group)).toEqual(Array(3).fill('Stock'));
  });

  it('names the leaves as owner-approved, and gives the picker names that stand alone', () => {
    const columns = byKey({ canSeeSales: true, canSeeMargin: true });
    const headers = (list) => list.map((key) => columns[key].header);
    expect(headers(['unidades_7d', 'unidades_30d', 'units_trend'])).toEqual(['7D', '30D', 'Tendencia']);
    expect(headers(['markup', 'markup_30d', 'markup_trend'])).toEqual(['Actual', 'Real 30D', 'Tendencia']);
    expect(headers(['facturado_30d', 'total_gauss_30d', 'last_sale', 'ageing'])).toEqual(['Facturado 30D', 'Total Gauss 30D', 'Última venta', 'Ageing']);
    expect(headers(['stock_erp', 'stock_full', 'stock_total'])).toEqual(['ERP', 'Full', 'Total']);
    const labels = (list) => list.map((key) => columns[key].label);
    expect(labels(['units_trend', 'markup', 'markup_trend', 'stock_erp', 'stock_full', 'stock_total'])).toEqual([
      'Tendencia de ventas',
      'Markup actual',
      'Tendencia de markup',
      'Stock ERP',
      'Stock Full',
      'Stock total',
    ]);
    // Never our own stock at ML: it is the published quantity, not real stock (owner, 2026-11-10).
    expect(columns.stock_propio).toBeUndefined();
  });

  it('sorts what /items sorts: Métricas’ figures over the whole set, the current markup, each stock on its own', () => {
    const sortable = buildColumns({ eventsEnabled: true, canSeeSales: true, canSeeMargin: true })
      .filter((column) => column.sortable)
      .map((column) => column.key);
    expect(sortable).toEqual([
      'titulo',
      'tipo',
      'precio',
      'unidades_7d',
      'unidades_30d',
      'markup',
      'markup_30d',
      'facturado_30d',
      'total_gauss_30d',
      'stock_erp',
      'stock_full',
      'stock_total',
      'codigo',
      'marca',
      'costo',
      'actividad',
    ]);
    expect(DEFAULT_DIRECTION.stock_total).toBe('desc');
    expect(DEFAULT_DIRECTION.stock_propio).toBeUndefined();
    // Clásica first, then 3, 6, 9 and 12 cuotas.
    expect(DEFAULT_DIRECTION.tipo).toBe('asc');
    for (const key of ['unidades_7d', 'unidades_30d', 'markup_30d', 'facturado_30d', 'total_gauss_30d']) {
      expect(DEFAULT_DIRECTION[key]).toBe('desc');
    }
  });
});

describe('listing type', () => {
  it('shows the listing type badge of each publication before its state', () => {
    const columns = byKey({});
    expect(columns.tipo.header).toBe('Tipo');
    render(<>{columns.tipo.render({ listing_kind: 'cuotas_3' })}</>);
    expect(screen.getByText('3 cuotas')).toBeInTheDocument();
  });

  // Owner (2026-11-12): Agrupado's parent rows sum up a brand in compact badges on one line ("C 33" … "12 24").
  it('gives Tipo and Estado room for the tree badges in Agrupado only; the list and Producto keep their widths', () => {
    const widths = (options) => {
      const columns = byKey(options);
      return [columns.tipo.width, columns.estado.width];
    };
    expect(widths({ agrupado: true })).toEqual([216, 128]);
    expect(widths({})).toEqual([110, 104]);
    expect(widths({ producto: true })).toEqual([110, 104]);
  });

  it('leaves the cell empty for a row the backend sends no listing kind for', () => {
    const { container } = render(<>{byKey({}).tipo.render({})}</>);
    expect(container).toBeEmptyDOMElement();
  });
});

const PPP = { costo: 850, moneda: 'ARS', fecha: '2026-02-14', markups: {} };
const SELL_IN = {
  sell_in: {
    compra_item_id: 1,
    descuento_unit: 100,
    costo: 39900,
    unidades_restantes: 2,
    moneda_costo: 'ARS',
    costo_moneda: 39900,
    descuento_unit_moneda: 100,
  },
  sell_out: null,
  markups_sell_in: {},
  markups_sell_in_out: {},
};

describe('product columns', () => {
  it('shows the linked product code and brand, and the cost in its own currency, as the panel shows it', () => {
    const columns = byKey({ canSeeMargin: true });
    const item = { link: { codigo: 'KB-HDMI', marca: 'Kabel' }, costo: { amount: 50, currency: 'USD' } };
    expect([columns.codigo.header, columns.marca.header, columns.costo.header]).toEqual(['Código', 'Marca', 'Costo']);
    render(
      <>
        <span>{columns.codigo.render(item)}</span>
        <span>{columns.marca.render(item)}</span>
        <span>{columns.costo.render(item)}</span>
      </>,
    );
    expect(screen.getByText('KB-HDMI')).toBeInTheDocument();
    expect(screen.getByText('Kabel')).toBeInTheDocument();
    expect(screen.getByText('USD 50,00')).toBeInTheDocument();
  });

  it('a publication without a product or cost reads a dash, never 0', () => {
    const columns = byKey({ canSeeMargin: true });
    render(<>{columns.codigo.render({ link: {} })}{columns.costo.render({ costo: null })}</>);
    expect(screen.getAllByText('—')).toHaveLength(2);
  });

  it('shows the cost with sell in inline on one line, the PPP in the tooltip (S10b)', () => {
    const columns = byKey({ canSeeMargin: true });
    const { container } = render(
      columns.costo.render({ costo: { amount: 40000, currency: 'ARS' }, ppp: PPP, sell_in_out: SELL_IN }),
    );
    expect(container.textContent).toBe('ARS 40.000,00 c/ sell in ARS 39.900,00');
    expect(container.firstChild.getAttribute('title')).toContain('ppp: ARS $850.00 (14/02/26)');
  });

  it('a product without a PPP row says "sin PPP" in the tooltip, and no sell in without one', () => {
    const columns = byKey({ canSeeMargin: true });
    const { container } = render(
      columns.costo.render({ costo: { amount: 40000, currency: 'ARS' }, ppp: null, sell_in_out: null }),
    );
    expect(container.textContent).toBe('ARS 40.000,00');
    expect(container.firstChild.getAttribute('title')).toBe('sin PPP');
  });

  it('without the margin fields the cell is the cost alone', () => {
    const columns = byKey({ canSeeMargin: true });
    const { container } = render(columns.costo.render({ costo: { amount: 50, currency: 'USD' } }));
    expect(container.textContent).toBe('USD 50,00');
  });

  it('sorts code and brand ascending and the cost cheapest first by default', () => {
    expect([DEFAULT_DIRECTION.codigo, DEFAULT_DIRECTION.marca, DEFAULT_DIRECTION.costo]).toEqual(['asc', 'asc', 'asc']);
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
    expect(keys({ canSeeMargin: true })).toEqual([
      'titulo', 'tipo', 'estado', 'precio', 'markup', 'stock_erp', 'stock_full', 'stock_total', 'codigo', 'marca', 'costo', 'vinculo', 'tienda', 'actividad',
    ]);
    // the cost, as in the panel, only with ver_ganancia
    expect(keys({})).toEqual(['titulo', 'tipo', 'estado', 'precio', 'stock_erp', 'stock_full', 'stock_total', 'codigo', 'marca', 'vinculo', 'tienda', 'actividad']);
  });

  it('with ml_metricas.ver but no ver_ganancia: units, gross and rotation, no markup and no Total Gauss', () => {
    const got = keys({ canSeeSales: true });
    expect(got).toEqual(expect.arrayContaining(['unidades_7d', 'unidades_30d', 'units_trend', 'facturado_30d', 'last_sale', 'ageing']));
    expect(got).not.toEqual(expect.arrayContaining(['markup']));
    for (const key of ['markup', 'markup_30d', 'markup_trend', 'total_gauss_30d']) expect(got).not.toContain(key);
  });
});

describe('the tree', () => {
  it('has no column a level leaves empty: the count lives in the first cell, Tipo/Estado/Precio follow it (S6)', () => {
    for (const view of [{ agrupado: true }, { producto: true }]) {
      const got = buildColumns({ eventsEnabled: false, canSeeSales: true, canSeeMargin: true, ...view });
      expect(got.slice(0, 4).map((column) => [column.key, column.group])).toEqual([
        ['titulo', undefined],
        ['tipo', undefined],
        ['estado', undefined],
        ['precio', undefined],
      ]);
      const keys = got.map((column) => column.key);
      expect(keys).not.toContain('publicaciones');
      expect(keys).not.toContain('negativos');
    }
  });
});

describe('default visibility', () => {
  it('hides Vínculo, Tienda, Última actividad and Último evento: they live in the Publicación cell and the panel', () => {
    expect(defaultColumnVisibility()).toEqual({
      codigo: false,
      marca: false,
      costo: false,
      vinculo: false,
      tienda: false,
      actividad: false,
      evento: false,
    });
  });

  it('keeps only the user’s own picks apart from the defaults', () => {
    const defaults = defaultColumnVisibility();
    expect(columnChoicesOver({ ...defaults, tienda: true, stock_full: false }, defaults)).toEqual({ tienda: true, stock_full: false });
  });
});
