/**
 * ODD `metricas-ml-agrupado-anidado` T4: the "Agrupado" view is a TREE. A node
 * opens lazily into the level below it (marca > categoría > subcategoría >
 * producto, ...), every level paged on its own, sorted like the board, under
 * the same filters and search, indented under its parent.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import {
  BOARD_RESPONSE,
  EPSON_CATEGORIAS,
  EPSON_GROUP_PRODUCTS,
  GROUP_BOARD_RESPONSE,
  IMPRESORAS_SUBCATEGORIAS,
  epsonNodesFor,
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

const NODES_URL = '/ml-metricas/board/group-nodes';
let nodeAnswer = (params) => epsonNodesFor(params.path);

beforeEach(() => {
  seedTiendasOficiales();
  nodeAnswer = (params) => epsonNodesFor(params.path);
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') {
      const grouped = config?.params?.group_by === 'group';
      return Promise.resolve({ data: grouped ? { ...GROUP_BOARD_RESPONSE, dimension: config.params.dimension } : BOARD_RESPONSE });
    }
    if (url === NODES_URL) return Promise.resolve({ data: nodeAnswer(config.params) });
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

const nodeCalls = () => api.get.mock.calls.filter(([url]) => url === NODES_URL);
const lastBoardParams = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board').at(-1)[1].params;
// The first match in document order: the node's own row (a leaf repeats its brand's name).
const rowOf = (text) => screen.getAllByText(text)[0].closest('tr');

async function openTree() {
  await renderWithRouter(<MetricasML />);
  await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
  await userEvent.click(screen.getByRole('button', { name: 'Agrupado' }));
  await screen.findByText('Sin marca');
}

async function openBranch() {
  await userEvent.click(screen.getByRole('button', { name: /Ver .* de Epson/ }));
  await screen.findByText('Impresoras');
  await userEvent.click(screen.getByRole('button', { name: /Ver .* de Impresoras/ }));
  await screen.findByText('Laser');
  await userEvent.click(screen.getByRole('button', { name: /Ver .* de Laser/ }));
  await screen.findByText(EPSON_GROUP_PRODUCTS.rows[0].title);
}

describe('the tree of levels', () => {
  it('names the whole chain of the dimension in the first column', async () => {
    await openTree();

    expect(screen.getByRole('columnheader', { name: 'Marca › Categoría › Subcategoría › Producto' })).toBeInTheDocument();
    const dimensions = screen.getByRole('group', { name: 'Dimensión' });
    const expected = {
      Categoría: 'Categoría › Subcategoría › Producto',
      Subcategoría: 'Subcategoría › Producto',
      Tienda: 'Tienda › Marca › Categoría › Subcategoría › Producto',
      PM: 'PM › Marca › Categoría › Subcategoría › Producto',
    };
    for (const [label, header] of Object.entries(expected)) {
      await userEvent.click(within(dimensions).getByRole('button', { name: label }));
      expect(await screen.findByRole('columnheader', { name: header })).toBeInTheDocument();
    }
  });

  it('opens one level at a time, each request carrying the path of keys down to the node', async () => {
    await openTree();

    await openBranch();

    expect(nodeCalls().map(([, c]) => c.params.path)).toEqual(['["EPSON"]', '["EPSON","IMPRESORAS"]', '["EPSON","IMPRESORAS","10"]']);
    for (const [, config] of nodeCalls()) {
      expect(config.params).toMatchObject({ group_by: 'group', dimension: 'marca', limit: 100, offset: 0 });
    }
  });

  it('shows every level under its parent, one step deeper each, with the name of its level', async () => {
    await openTree();
    await openBranch();

    const depths = Object.fromEntries(
      ['Epson', 'Impresoras', 'Laser', EPSON_GROUP_PRODUCTS.rows[0].title].map((text) => [text, rowOf(text).dataset.depth]),
    );
    expect(depths).toEqual({
      Epson: '0',
      Impresoras: '1',
      Laser: '2',
      [EPSON_GROUP_PRODUCTS.rows[0].title]: '3',
    });
    // Each level steps in further than its parent (the cell's `--indent`).
    const indent = (text) => rowOf(text).querySelector('td[data-col-id="producto"] > div').style.getPropertyValue('--indent');
    expect(['Epson', 'Impresoras', 'Laser'].map(indent)).toEqual(['0px', '18px', '36px']);
    expect(within(rowOf('Impresoras')).getByText('Categoría')).toBeInTheDocument();
    expect(within(rowOf('Laser')).getByText('Subcategoría')).toBeInTheDocument();
    expect(within(rowOf('Epson')).getByText('Marca')).toBeInTheDocument();
    // The rows keep the board's metrics at every level.
    expect(rowOf('Impresoras').querySelector('td[data-col-id="units_30d"]')).toHaveTextContent('700');
    expect(within(rowOf('Impresoras')).getByText('9 productos · 24 publicaciones')).toBeInTheDocument();
    expect(rowOf('Sin subcategoría')).toBeInTheDocument();
  });

  it('opening a node below the top never reloads the levels above it', async () => {
    await openTree();
    await openBranch();

    expect(nodeCalls()).toHaveLength(3);
    expect(api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board')).toHaveLength(2); // product view + group view
  });

  it('collapsing a node hides everything under it and opening it again reuses what it loaded', async () => {
    await openTree();
    await openBranch();

    await userEvent.click(screen.getByRole('button', { name: /Ocultar .* de Epson/ }));

    expect(screen.queryByText('Impresoras')).not.toBeInTheDocument();
    expect(screen.queryByText('Laser')).not.toBeInTheDocument();
    expect(screen.queryByText(EPSON_GROUP_PRODUCTS.rows[0].title)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Ver .* de Epson/ }));

    // The branch comes back as it was (its inner nodes stay open) with no new request.
    expect(await screen.findByText(EPSON_GROUP_PRODUCTS.rows[0].title)).toBeInTheDocument();
    expect(nodeCalls()).toHaveLength(3);
  });

  it('the same key under two parents is two different nodes (a subcategoría in two categorías)', async () => {
    const twin = (path) => {
      if (path === '["EPSON"]') return EPSON_CATEGORIAS;
      if (path === '["EPSON","IMPRESORAS"]' || path === '["EPSON","INSUMOS"]') {
        return { ...IMPRESORAS_SUBCATEGORIAS, rows: [IMPRESORAS_SUBCATEGORIAS.rows[0]] };
      }
      return { level: 'product', rows: [], total: 0, limit: 100, offset: 0 };
    };
    nodeAnswer = (params) => twin(params.path);
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    await openTree();
    await userEvent.click(screen.getByRole('button', { name: /Ver .* de Epson/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Ver .* de Impresoras/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Ver .* de Insumos/ }));

    await waitFor(() => expect(screen.getAllByText('Laser')).toHaveLength(2));
    expect(errors.mock.calls.flat().join(' ')).not.toMatch(/same key/);
    // Opening one of them opens only that one.
    await userEvent.click(within(rowOf('Impresoras').parentElement.querySelectorAll('tr')[2]).getByRole('button', { name: /Ver .* de Laser/ }));
    expect(nodeCalls().at(-1)[1].params.path).toBe('["EPSON","IMPRESORAS","10"]');
    errors.mockRestore();
  });
});

describe('paging, sorting and search at every level', () => {
  const page = (level, child, count, total, from = 0) => ({
    level,
    rows: Array.from({ length: count }, (_, i) => ({
      ...EPSON_CATEGORIAS.rows[0],
      key: `K${from + i}`,
      title: `${level} ${from + i}`,
      level,
      child_level: child,
    })),
    total,
    limit: 100,
    offset: from,
  });

  it('each level pages on its own: "Ver más" asks the next page of THAT node only', async () => {
    nodeAnswer = (params) => {
      if (params.path === '["EPSON"]') return params.offset ? page('categoria', 'subcategoria', 1, 101, 100) : page('categoria', 'subcategoria', 100, 101);
      return page('subcategoria', 'product', 2, 2);
    };
    await openTree();
    await userEvent.click(screen.getByRole('button', { name: /Ver .* de Epson/ }));
    await screen.findByText('categoria 0');
    await userEvent.click(screen.getByRole('button', { name: /Ver .* de categoria 0/ }));
    await screen.findByText('subcategoria 0');

    expect(screen.getByText('Mostrando 100 de 101 categorías')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ver más categorías' }));

    expect(await screen.findByText('categoria 100')).toBeInTheDocument();
    const last = nodeCalls().at(-1)[1].params;
    expect(last).toMatchObject({ path: '["EPSON"]', offset: 100 });
    // The open child kept its own rows and did not ask again.
    expect(screen.getByText('subcategoria 1')).toBeInTheDocument();
    expect(nodeCalls().filter(([, c]) => c.params.path === '["EPSON","K0"]')).toHaveLength(1);
  });

  it('every level is asked with the board\'s sort', async () => {
    await openTree();
    await userEvent.click(within(screen.getByRole('columnheader', { name: /^30D/ })).getByRole('button'));
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ sort: 'units_30d' }));

    await openBranch();

    for (const [, config] of nodeCalls()) {
      expect(config.params).toMatchObject({ sort: 'units_30d', sort_dir: 'desc' });
    }
  });

  it('changing the sort closes the tree and the next opening uses the new order', async () => {
    await openTree();
    await openBranch();

    await userEvent.click(within(screen.getByRole('columnheader', { name: /^Marca/ })).getByRole('button'));

    await waitFor(() => expect(screen.queryByText('Laser')).not.toBeInTheDocument());
    await userEvent.click(await screen.findByRole('button', { name: /Ver .* de Epson/ }));
    await waitFor(() => expect(nodeCalls().at(-1)[1].params).toMatchObject({ sort: 'title', sort_dir: 'asc' }));
  });

  it('the search narrows every level: it travels with each request and closes the open branches', async () => {
    await openTree();
    await openBranch();

    await userEvent.type(screen.getByPlaceholderText(/Buscar por producto/), 'notebook');

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ q: 'notebook' }));
    await waitFor(() => expect(screen.queryByText('Laser')).not.toBeInTheDocument());
    await userEvent.click(await screen.findByRole('button', { name: /Ver .* de Epson/ }));
    await waitFor(() => expect(nodeCalls().at(-1)[1].params).toMatchObject({ q: 'notebook', path: '["EPSON"]' }));
  });

  it('an empty level says so instead of leaving a blank', async () => {
    nodeAnswer = () => ({ level: 'categoria', rows: [], total: 0, limit: 100, offset: 0 });
    await openTree();

    await userEvent.click(screen.getByRole('button', { name: /Ver .* de Epson/ }));

    expect(await screen.findByText('No hay categorías para estos filtros.')).toBeInTheDocument();
  });

  it('a level that fails to load says which one and retries on its own', async () => {
    let fail = true;
    nodeAnswer = (params) => {
      if (params.path === '["EPSON","IMPRESORAS"]' && fail) throw new Error('boom');
      return epsonNodesFor(params.path);
    };
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board') {
        return Promise.resolve({ data: config.params.group_by === 'group' ? GROUP_BOARD_RESPONSE : BOARD_RESPONSE });
      }
      if (url === NODES_URL) {
        try {
          return Promise.resolve({ data: nodeAnswer(config.params) });
        } catch (err) {
          return Promise.reject(err);
        }
      }
      return Promise.resolve({ data: {} });
    });
    await openTree();
    await userEvent.click(screen.getByRole('button', { name: /Ver .* de Epson/ }));
    await screen.findByText('Impresoras');

    await userEvent.click(screen.getByRole('button', { name: /Ver .* de Impresoras/ }));

    expect(await screen.findByText('No se pudieron cargar las subcategorías.')).toBeInTheDocument();
    expect(screen.getByText('Insumos')).toBeInTheDocument(); // its sibling is untouched
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: /Ocultar .* de Impresoras/ }));
    await userEvent.click(screen.getByRole('button', { name: /Ver .* de Impresoras/ }));
    expect(await screen.findByText('Laser')).toBeInTheDocument();
  });
});

describe('permissions at every level', () => {
  it('without the margin permission no level shows Total Gauss or markup', async () => {
    const strip = (rows) => rows.map((r) => ({ ...r, total_gauss: null, markup_pct: null, markup_delta_pp: null }));
    nodeAnswer = (params) => {
      const answer = epsonNodesFor(params.path);
      return { ...answer, rows: strip(answer.rows) };
    };
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board') {
        return Promise.resolve({
          data: config.params.group_by === 'group'
            ? { ...GROUP_BOARD_RESPONSE, can_see_margin: false, rows: strip(GROUP_BOARD_RESPONSE.rows) }
            : BOARD_RESPONSE,
        });
      }
      if (url === NODES_URL) return Promise.resolve({ data: nodeAnswer(config.params) });
      return Promise.resolve({ data: {} });
    });
    await openTree();

    await openBranch();

    expect(screen.queryByRole('columnheader', { name: /Total Gauss/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/markup$/)).not.toBeInTheDocument();
  });
});
