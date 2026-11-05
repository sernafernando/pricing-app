/**
 * Métricas ML's "Todos" (filas-sin-limite S3): every row of the board, no cap. Like Publicaciones ML's "Todos", the
 * rows come in parts as the table's end comes into view, until the board's total, in one page.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE, BOARD_ROWS } from '../test/visual/metricasMlFixtures';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

// jsdom lays nothing out: the page "shows" every row, so each part's end is in view as soon as it renders.
vi.mock('@tanstack/react-virtual', async (importOriginal) => ({
  ...(await importOriginal()),
  useVirtualizer: (options) => {
    const items = Array.from({ length: options.count }, (_, index) => ({
      index,
      key: options.getItemKey(index),
      start: index * 56,
      end: (index + 1) * 56,
    }));
    return { getVirtualItems: () => items, getTotalSize: () => options.count * 56, measureElement: () => {}, options };
  },
}));

const TOTAL = 4500;
// The first part: 101 rows (past the 100 the board virtualizes from); the next ones, two rows of their own offset.
const part = (offset) =>
  offset === 0
    ? [...BOARD_ROWS, ...Array.from({ length: 101 - BOARD_ROWS.length }, (_, i) => row(90000 + i))]
    : [row(offset), row(offset + 1)];
const row = (key) => ({ ...BOARD_ROWS[0], key: String(key), product_item_id: key, title: `Producto ${key}` });
let failOnce = null;

beforeEach(() => {
  seedTiendasOficiales();
  failOnce = null;
  api.get.mockReset();
  api.get.mockImplementation((url, { params } = {}) => {
    if (url === '/ml-metricas/board') {
      if (failOnce === params.offset) {
        failOnce = null;
        return Promise.reject(Object.assign(new Error('503'), { response: { status: 503 } }));
      }
      if (params.limit !== 2000) return Promise.resolve({ data: BOARD_RESPONSE });
      return Promise.resolve({ data: { ...BOARD_RESPONSE, total: TOTAL, limit: params.limit, offset: params.offset, rows: part(params.offset) } });
    }
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});
afterAll(resetTiendasOficiales);

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board').map(([, { params }]) => params);
const todosCalls = () => boardCalls().filter((params) => params.limit === 2000);

async function chooseTodos() {
  await renderWithRouter(<MetricasML />);
  await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
  await userEvent.selectOptions(screen.getByLabelText('Filas por página'), 'Todos');
}

describe('Métricas ML "Todos"', () => {
  it('the page sizes keep 25, 50, 100 and 200 and add "Todos"', async () => {
    await renderWithRouter(<MetricasML />);
    const select = await screen.findByLabelText('Filas por página');
    expect(within(select).getAllByRole('option').map((option) => option.textContent)).toEqual([
      '25',
      '50',
      '100',
      '200',
      'Todos',
    ]);
  });

  it('asks parts of 2000 from the first row, with the same filters and sort, until the whole total, in one page', async () => {
    await chooseTodos();
    await waitFor(() => expect(todosCalls()).toHaveLength(3));
    const [first, second, third] = todosCalls();
    expect(first).toMatchObject({ limit: 2000, offset: 0, sort: 'gross', sort_dir: 'desc' });
    expect(second).toEqual({ ...first, offset: 2000 });
    expect(third).toEqual({ ...first, offset: 4000 });
    expect(await screen.findByText('Producto 4001')).toBeInTheDocument();
    expect(screen.getByText('Producto 2000')).toBeInTheDocument();
    expect(screen.getByText(/^Mostrando/).textContent.replace(/\s+/g, ' ')).toMatch(/^Mostrando 1–4500 de 4\.500 productos/);
    expect(screen.queryByRole('button', { name: 'Página 2' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled();
  });

  it('a failed part says so and "Reintentar" asks it again, so the list is never cut short in silence', async () => {
    failOnce = 2000;
    await chooseTodos();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('No se pudieron traer más productos');
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByText('Producto 4001')).toBeInTheDocument();
    expect(todosCalls().filter((params) => params.offset === 2000)).toHaveLength(2);
  });

  it('going back to a page size asks one request of that size', async () => {
    await chooseTodos();
    await waitFor(() => expect(todosCalls()).toHaveLength(3));
    await userEvent.selectOptions(screen.getByLabelText('Filas por página'), '50');
    await waitFor(() => expect(boardCalls().at(-1)).toMatchObject({ limit: 50, offset: 0 }));
  });
});
