/**
 * ODD `metricas-ml-vista-agrupada` T4/T5: the third view of the Métricas ML
 * board, "Agrupado" -- rows summed by marca, categoría, subcategoría, tienda or
 * PM (`group_by=group&dimension=...`), each opening into its products.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { exportMetricasCsv } from '../utils/ventasMlExport';
import {
  BOARD_RESPONSE,
  EPSON_GROUP_PRODUCTS,
  GROUP_BOARD_RESPONSE,
} from '../test/visual/metricasMlFixtures';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../utils/ventasMlExport', async (importOriginal) => ({
  ...(await importOriginal()),
  exportMetricasCsv: vi.fn(() => Promise.resolve()),
}));

const GROUP_PRODUCTS_URL = '/ml-metricas/board/group-products';
let groupBoard = GROUP_BOARD_RESPONSE;
let groupProducts = EPSON_GROUP_PRODUCTS;

beforeEach(() => {
  seedTiendasOficiales();
  groupBoard = GROUP_BOARD_RESPONSE;
  groupProducts = EPSON_GROUP_PRODUCTS;
  vi.mocked(exportMetricasCsv).mockClear();
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') {
      const grouped = config?.params?.group_by === 'group';
      return Promise.resolve({ data: grouped ? { ...groupBoard, dimension: config.params.dimension } : BOARD_RESPONSE });
    }
    if (url === GROUP_PRODUCTS_URL) return Promise.resolve({ data: groupProducts });
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board');
const lastBoardParams = () => boardCalls().at(-1)[1].params;
const productCalls = () => api.get.mock.calls.filter(([url]) => url === GROUP_PRODUCTS_URL);

async function openGroupedView() {
  await renderWithRouter(<MetricasML />);
  await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
  await userEvent.click(screen.getByRole('button', { name: 'Agrupado' }));
  await screen.findByText('Sin marca');
}

describe('the "Agrupado" view', () => {
  it('is offered next to Producto and Publicación and asks for group_by=group by marca, from page 1', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    const views = screen.getByRole('group', { name: 'Agrupar por' });
    expect(within(views).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Producto',
      'Publicación',
      'Agrupado',
    ]);
    // The dimension picker only exists under "Agrupado".
    expect(screen.queryByRole('group', { name: 'Dimensión' })).not.toBeInTheDocument();
    expect(lastBoardParams()).not.toHaveProperty('dimension');

    await userEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
    await userEvent.click(within(views).getByRole('button', { name: 'Agrupado' }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ group_by: 'group', dimension: 'marca', offset: 0 }));
  });

  it('offers the five dimensions, each reaching the request and returning to page 1', async () => {
    await openGroupedView();
    const dimensions = screen.getByRole('group', { name: 'Dimensión' });
    expect(within(dimensions).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Marca',
      'Categoría',
      'Subcategoría',
      'Tienda',
      'PM',
    ]);

    for (const [label, value] of [
      ['Categoría', 'categoria'],
      ['Subcategoría', 'subcategoria'],
      ['Tienda', 'tienda'],
      ['PM', 'pm'],
      ['Marca', 'marca'],
    ]) {
      await userEvent.click(within(dimensions).getByRole('button', { name: label }));
      await waitFor(() => expect(lastBoardParams()).toMatchObject({ group_by: 'group', dimension: value, offset: 0 }));
    }
  });

  it('leaving it drops the dimension from the request', async () => {
    await openGroupedView();

    await userEvent.click(screen.getByRole('button', { name: 'Publicación' }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ group_by: 'publication' }));
    expect(lastBoardParams()).not.toHaveProperty('dimension');
  });

  it('renders one row per group with its counts, windows, markup, ageing and stock', async () => {
    await openGroupedView();

    const row = screen.getByText('Epson').closest('tr');
    const cells = within(row);
    expect(cells.getByText('12 productos · 31 publicaciones')).toBeInTheDocument();
    expect(cells.getByText('20,3%')).toBeInTheDocument();
    expect(cells.getByText('▲ +1,4 pp')).toBeInTheDocument();
    expect(row.querySelector('td[data-col-id="stock"]')).toHaveTextContent('1.340');
    expect(row.querySelector('td[data-col-id="units_30d"]')).toHaveTextContent('842');
    // A group with no stock figure and no sales reads like an empty row, not an error.
    const none = screen.getByText('Sin marca').closest('tr');
    expect(none.querySelector('td[data-col-id="stock"]')).toHaveTextContent('—');
  });

  it('group rows carry no alert or loss badges', async () => {
    groupBoard = {
      ...GROUP_BOARD_RESPONSE,
      rows: GROUP_BOARD_RESPONSE.rows.map((r) => ({ ...r, alerts: ['sin_ventas_30d', 'ageing_60d'], markup_pct: -5 })),
    };
    await openGroupedView();

    expect(screen.queryByText('INMOVILIZADO')).not.toBeInTheDocument();
    expect(screen.queryByText('PÉRDIDA')).not.toBeInTheDocument();
  });

  it('titles the first column after the dimension', async () => {
    await openGroupedView();

    expect(screen.getByRole('columnheader', { name: /^Marca/ })).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole('group', { name: 'Dimensión' })).getByRole('button', { name: 'PM' }));
    expect(await screen.findByRole('columnheader', { name: /^PM/ })).toBeInTheDocument();
  });

  it('sorts by its columns, the first one by name', async () => {
    await openGroupedView();

    await userEvent.click(within(screen.getByRole('columnheader', { name: /^30D/ })).getByRole('button'));
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ sort: 'units_30d', sort_dir: 'desc' }));

    await userEvent.click(within(screen.getByRole('columnheader', { name: /^Marca/ })).getByRole('button'));
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ sort: 'title', sort_dir: 'asc' }));
  });

  it('counts groups in the KPI card and in the pager', async () => {
    await openGroupedView();

    expect(screen.getByText('Grupos con ventas')).toBeInTheDocument();
    expect(screen.getByText(/Mostrando/)).toHaveTextContent(/de\s*3\s*grupos/);
  });

  it('keeps the shared filters: they travel with the grouped request', async () => {
    await openGroupedView();

    await userEvent.click(
      within(screen.getByRole('group', { name: 'Filtrar por tienda oficial' })).getByRole('button', { name: /TP-Link/ }),
    );

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ group_by: 'group', stores: '2645', dimension: 'marca' }));
  });

  it('without the margin permission the groups show no Total Gauss or markup', async () => {
    groupBoard = {
      ...GROUP_BOARD_RESPONSE,
      can_see_margin: false,
      rows: GROUP_BOARD_RESPONSE.rows.map((r) => ({ ...r, total_gauss: null, markup_pct: null })),
    };
    await openGroupedView();

    expect(screen.queryByRole('columnheader', { name: /Total Gauss/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Markup act/i })).not.toBeInTheDocument();
  });

  it('exports the grouped view with its dimension', async () => {
    await openGroupedView();
    await userEvent.click(within(screen.getByRole('group', { name: 'Dimensión' })).getByRole('button', { name: 'Tienda' }));
    await waitFor(() => expect(lastBoardParams().dimension).toBe('tienda'));

    await userEvent.click(screen.getByRole('button', { name: /Exportar CSV/ }));

    await waitFor(() => expect(exportMetricasCsv).toHaveBeenCalled());
    expect(exportMetricasCsv.mock.calls[0][0]).toMatchObject({ group_by: 'group', dimension: 'tienda' });
  });
});

describe('opening a group', () => {
  const expandButton = () => screen.getByRole('button', { name: /productos de Epson/ });

  it('loads its products under the same filters and the group key, and lists them as sub-rows', async () => {
    await openGroupedView();

    await userEvent.click(expandButton());

    const first = EPSON_GROUP_PRODUCTS.rows[0];
    expect(await screen.findByText(first.title)).toBeInTheDocument();
    expect(screen.getByText(first.sku)).toBeInTheDocument();
    expect(productCalls()).toHaveLength(1);
    const params = productCalls()[0][1].params;
    expect(params).toMatchObject({
      group_by: 'group',
      dimension: 'marca',
      group_key: 'EPSON',
      comparar_con: 'periodo_anterior',
      date_from: lastBoardParams().date_from,
      limit: 100,
      offset: 0,
    });
    expect(expandButton()).toHaveAttribute('aria-expanded', 'true');
  });

  it('opens a group whose key has special characters and the "sin" group', async () => {
    await openGroupedView();

    await userEvent.click(screen.getByRole('button', { name: /Ver productos de Sin marca/ }));

    await waitFor(() => expect(productCalls().at(-1)[1].params.group_key).toBe('__none__'));
  });

  it('pages: "Ver más" asks for the next page and appends it', async () => {
    const page2 = {
      rows: [{ ...EPSON_GROUP_PRODUCTS.rows[0], key: '9999', product_item_id: 9999, title: 'Producto de la página dos' }],
      total: 12,
      limit: 100,
      offset: 100,
    };
    const fullPage = {
      rows: Array.from({ length: 100 }, (_, i) => ({ ...EPSON_GROUP_PRODUCTS.rows[0], key: `p${i}`, title: `Producto ${i}` })),
      total: 101,
      limit: 100,
      offset: 0,
    };
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board') {
        return Promise.resolve({ data: config.params.group_by === 'group' ? GROUP_BOARD_RESPONSE : BOARD_RESPONSE });
      }
      if (url === GROUP_PRODUCTS_URL) {
        return Promise.resolve({ data: config.params.offset === 100 ? page2 : fullPage });
      }
      return Promise.resolve({ data: {} });
    });
    await openGroupedView();
    await userEvent.click(expandButton());
    await screen.findByText('Producto 0');

    await userEvent.click(screen.getByRole('button', { name: /Ver más productos/ }));

    expect(await screen.findByText('Producto de la página dos')).toBeInTheDocument();
    expect(screen.getByText('Producto 99')).toBeInTheDocument();
    expect(productCalls().at(-1)[1].params.offset).toBe(100);
  });

  it('a failed next page keeps what was loaded and offers to retry just that page', async () => {
    const fullPage = {
      rows: Array.from({ length: 100 }, (_, i) => ({ ...EPSON_GROUP_PRODUCTS.rows[0], key: `p${i}`, title: `Producto ${i}` })),
      total: 150,
      limit: 100,
      offset: 0,
    };
    let failSecond = true;
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board') {
        return Promise.resolve({ data: config.params.group_by === 'group' ? GROUP_BOARD_RESPONSE : BOARD_RESPONSE });
      }
      if (url === GROUP_PRODUCTS_URL) {
        if (config.params.offset === 0) return Promise.resolve({ data: fullPage });
        return failSecond
          ? Promise.reject(new Error('boom'))
          : Promise.resolve({ data: { ...fullPage, rows: [{ ...fullPage.rows[0], key: 'q', title: 'Producto 100' }], offset: 100 } });
      }
      return Promise.resolve({ data: {} });
    });
    await openGroupedView();
    await userEvent.click(expandButton());
    await screen.findByText('Producto 0');
    await userEvent.click(screen.getByRole('button', { name: /Ver más productos/ }));

    expect(await screen.findByText('No se pudieron cargar los productos.')).toBeInTheDocument();
    expect(screen.getByText('Producto 99')).toBeInTheDocument();
    failSecond = false;
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));

    expect(await screen.findByText('Producto 100')).toBeInTheDocument();
    expect(productCalls().at(-1)[1].params.offset).toBe(100);
  });

  it('a second page that overlaps the first (the order moved meanwhile) never repeats a row', async () => {
    const rows = Array.from({ length: 100 }, (_, i) => ({ ...EPSON_GROUP_PRODUCTS.rows[0], key: `p${i}`, title: `Producto ${i}` }));
    const shifted = { rows: [rows[99], { ...rows[0], key: 'p100', title: 'Producto 100' }], total: 101, limit: 100, offset: 100 };
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board') {
        return Promise.resolve({ data: config.params.group_by === 'group' ? GROUP_BOARD_RESPONSE : BOARD_RESPONSE });
      }
      if (url === GROUP_PRODUCTS_URL) {
        return Promise.resolve({ data: config.params.offset === 100 ? shifted : { rows, total: 101, limit: 100, offset: 0 } });
      }
      return Promise.resolve({ data: {} });
    });
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    await openGroupedView();
    await userEvent.click(expandButton());
    await screen.findByText('Producto 0');

    await userEvent.click(screen.getByRole('button', { name: /Ver más productos/ }));

    expect(await screen.findByText('Producto 100')).toBeInTheDocument();
    expect(screen.getAllByText('Producto 99')).toHaveLength(1);
    expect(errors.mock.calls.flat().join(' ')).not.toMatch(/same key/);
    errors.mockRestore();
  });

  it('the next page starts where the SERVER left off, even when a repeated row was dropped', async () => {
    const make = (from) => Array.from({ length: 100 }, (_, i) => ({ ...EPSON_GROUP_PRODUCTS.rows[0], key: `p${from + i}`, title: `Producto ${from + i}` }));
    const pages = { 0: make(0), 100: [make(0)[99], ...make(100).slice(1)], 200: make(200) };
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board') {
        return Promise.resolve({ data: config.params.group_by === 'group' ? GROUP_BOARD_RESPONSE : BOARD_RESPONSE });
      }
      if (url === GROUP_PRODUCTS_URL) return Promise.resolve({ data: { rows: pages[config.params.offset] ?? [], total: 300, limit: 100 } });
      return Promise.resolve({ data: {} });
    });
    await openGroupedView();
    await userEvent.click(expandButton());
    await screen.findByText('Producto 0');
    await userEvent.click(screen.getByRole('button', { name: /Ver más productos/ }));
    await screen.findByText('Producto 199');
    await userEvent.click(screen.getByRole('button', { name: /Ver más productos/ }));

    await waitFor(() => expect(productCalls().map(([, c]) => c.params.offset)).toEqual([0, 100, 200]));
  });

  it('the same product under two open groups (a product sold in two stores) never repeats a React key', async () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    await openGroupedView();

    await userEvent.click(screen.getByRole('button', { name: /productos de Epson/ }));
    await userEvent.click(screen.getByRole('button', { name: /productos de Lenovo/ }));

    await waitFor(() => expect(screen.getAllByText(EPSON_GROUP_PRODUCTS.rows[0].title)).toHaveLength(2));
    expect(errors.mock.calls.flat().join(' ')).not.toMatch(/same key/);
    errors.mockRestore();
  });

  it('shows no "Ver más" once every product is on screen', async () => {
    groupProducts = { ...EPSON_GROUP_PRODUCTS, total: 2 };
    await openGroupedView();

    await userEvent.click(expandButton());
    await screen.findByText(EPSON_GROUP_PRODUCTS.rows[0].title);

    expect(screen.queryByRole('button', { name: /Ver más productos/ })).not.toBeInTheDocument();
  });

  it('a failed load is not cached: collapsing and opening again retries', async () => {
    let fail = true;
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board') {
        return Promise.resolve({ data: config.params.group_by === 'group' ? GROUP_BOARD_RESPONSE : BOARD_RESPONSE });
      }
      if (url === GROUP_PRODUCTS_URL) return fail ? Promise.reject(new Error('boom')) : Promise.resolve({ data: EPSON_GROUP_PRODUCTS });
      return Promise.resolve({ data: {} });
    });
    await openGroupedView();

    await userEvent.click(expandButton());
    expect(await screen.findByText('No se pudieron cargar los productos.')).toBeInTheDocument();
    fail = false;
    await userEvent.click(expandButton());
    await userEvent.click(expandButton());

    expect(await screen.findByText(EPSON_GROUP_PRODUCTS.rows[0].title)).toBeInTheDocument();
    expect(productCalls()).toHaveLength(2);
  });

  it('changing a filter closes the open groups and never shows the old filters\' products', async () => {
    await openGroupedView();
    await userEvent.click(expandButton());
    await screen.findByText(EPSON_GROUP_PRODUCTS.rows[0].title);

    await userEvent.click(within(screen.getByRole('group', { name: 'Dimensión' })).getByRole('button', { name: 'Categoría' }));

    await waitFor(() => expect(screen.queryByText(EPSON_GROUP_PRODUCTS.rows[0].title)).not.toBeInTheDocument());
  });
});
