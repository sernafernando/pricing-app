/**
 * ODD `metricas-ml-tablero` T4: the Métricas ML page wiring -- what it asks
 * the board endpoint for, and what it does with the answer. Layout is the
 * visual suite's job (`src/test/visual/metricasMl.visual.test.jsx`).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE, EPSON_PUBLICATIONS } from '../test/visual/metricasMlFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

let board = BOARD_RESPONSE;

beforeEach(() => {
  board = BOARD_RESPONSE;
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/ml-metricas/board') return Promise.resolve({ data: board });
    if (url === '/ml-metricas/board/products/4101/publications') return Promise.resolve({ data: EPSON_PUBLICATIONS });
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board');
const lastBoardParams = () => boardCalls().at(-1)[1].params;

describe('MetricasML page', () => {
  it('asks for the last 30 days by product, compared with the previous period, sorted by gross', async () => {
    await renderWithRouter(<MetricasML />);

    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(lastBoardParams()).toMatchObject({
      group_by: 'product',
      comparar_con: 'periodo_anterior',
      sort: 'gross',
      sort_dir: 'desc',
      limit: 50,
      offset: 0,
    });
    expect(lastBoardParams().date_from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('renders one row per product with its windows, markup and delta', async () => {
    await renderWithRouter(<MetricasML />);

    const row = (await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro')).closest('tr');
    const cells = within(row);
    expect(cells.getByText('EPS-L3250')).toBeInTheDocument();
    expect(cells.getByText('3 publicaciones')).toBeInTheDocument();
    expect(cells.getByText('21,6%')).toBeInTheDocument();
    expect(cells.getByText('▲ +2,1 pp')).toBeInTheDocument();
    expect(cells.getByText('18,4% / 23,2%')).toBeInTheDocument();
    expect(cells.getByText('$ 204.313.765,38')).toBeInTheDocument();
    expect(screen.getByText('PÉRDIDA')).toBeInTheDocument();
    expect(screen.getByText('INMOVILIZADO')).toBeInTheDocument();
  });

  it('expanding a product loads its publications with the same filters and marks the best one', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');

    await userEvent.click(screen.getByRole('button', { name: /Ver publicaciones de Impresora Multifunción Epson/ }));

    const best = (await screen.findByText('MLA2060835678')).closest('tr');
    expect(within(best).getByText('Mejor')).toBeInTheDocument();
    expect(within(best).getByText('Clásica · Full · Activa')).toBeInTheDocument();
    const call = api.get.mock.calls.find(([url]) => url === '/ml-metricas/board/products/4101/publications');
    expect(call[1].params).toMatchObject({ comparar_con: 'periodo_anterior', date_from: lastBoardParams().date_from });
    expect(call[1].params.limit).toBeUndefined();
  });

  it('switching to "Publicación" groups by publication and returns to page 1', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');

    await userEvent.click(screen.getByRole('button', { name: 'Publicación' }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ group_by: 'publication', offset: 0 }));
  });

  it('store, publication status, type and alert chips all reach the request', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');

    await userEvent.click(within(screen.getByRole('group', { name: 'Filtrar por tienda oficial' })).getByRole('button', { name: /TP-Link Oficial/ }));
    await userEvent.click(screen.getByRole('button', { name: /Pausada/ }));
    await userEvent.click(screen.getByRole('button', { name: /^Full/ }));
    await userEvent.click(screen.getByRole('button', { name: /Sin ventas 30d/ }));

    await waitFor(() =>
      expect(lastBoardParams()).toMatchObject({
        stores: '2645',
        pub_status: 'paused',
        pub_type: 'full',
        alerts: 'sin_ventas_30d',
      }),
    );
  });

  it('"Comparar con" switches to the same period last year', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');

    await userEvent.click(screen.getByRole('button', { name: 'Mismo período año pasado' }));

    await waitFor(() => expect(lastBoardParams().comparar_con).toBe('anio_anterior'));
  });

  it('pages with the shared pager', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    expect(screen.getByText(/^Mostrando/).textContent.replace(/\s+/g, ' ')).toBe(
      'Mostrando 1–50 de 471 productos (318 con rotación en el período)',
    );

    await userEvent.click(screen.getByRole('button', { name: 'Siguiente' }));

    await waitFor(() => expect(lastBoardParams().offset).toBe(50));
  });

  it('without the margin permission there are no Total Gauss or markup columns', async () => {
    board = { ...BOARD_RESPONSE, can_see_margin: false };
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');

    expect(screen.queryByRole('columnheader', { name: /Total Gauss/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Markup act/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Markup cayendo/ })).not.toBeInTheDocument();
  });

  it('sell-in / sell-out is announced, not invented', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');

    expect(screen.getByText('Próximamente')).toBeInTheDocument();
  });
});
