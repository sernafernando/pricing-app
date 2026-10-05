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

  it('a second click on a status chip hides it: pub_status_exclude replaces pub_status', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');

    await userEvent.click(screen.getByRole('button', { name: /Pausada/ }));
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ pub_status: 'paused' }));
    await userEvent.click(screen.getByRole('button', { name: /Pausada/ }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ pub_status_exclude: 'paused' }));
    expect(lastBoardParams()).not.toHaveProperty('pub_status');
    expect(screen.getByRole('button', { name: /^Ocultar Pausada · \d/ })).toBeInTheDocument();
  });

  it('type chips can be hidden too, and the exclusion reaches the nested publications', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');

    await userEvent.click(screen.getByRole('button', { name: /^Catálogo/ }));
    await userEvent.click(screen.getByRole('button', { name: /^Catálogo/ }));
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ pub_type_exclude: 'catalogo' }));
    await userEvent.click(screen.getByRole('button', { name: /Ver publicaciones de Impresora Multifunción Epson/ }));

    await waitFor(() => {
      const call = api.get.mock.calls.find(([url]) => url === '/ml-metricas/board/products/4101/publications');
      expect(call[1].params).toMatchObject({ pub_type_exclude: 'catalogo' });
    });
  });

  it('"Limpiar filtros" also clears the excluded chips', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    await userEvent.click(screen.getByRole('button', { name: /Pausada/ }));
    await userEvent.click(screen.getByRole('button', { name: /Pausada/ }));
    await userEvent.click(screen.getByRole('button', { name: /^Full/ }));
    await userEvent.click(screen.getByRole('button', { name: /^Full/ }));
    await waitFor(() =>
      expect(lastBoardParams()).toMatchObject({ pub_status_exclude: 'paused', pub_type_exclude: 'full' }),
    );

    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));

    await waitFor(() => expect(lastBoardParams()).not.toHaveProperty('pub_status_exclude'));
    expect(lastBoardParams()).not.toHaveProperty('pub_type_exclude');
    expect(screen.getByRole('button', { name: /Pausada/ })).toHaveAttribute('data-state', 'neutral');
  });

  it('"Solo con ventas en el período" is on by default and turning it off asks for the whole catalog', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    expect(lastBoardParams().solo_con_ventas).toBe(true);
    const toggle = screen.getByRole('switch', { name: /Solo con ventas en el período/ });
    expect(toggle).toHaveAttribute('aria-checked', 'true');

    await userEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
    await waitFor(() => expect(lastBoardParams().offset).toBe(50));
    await userEvent.click(toggle);

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ solo_con_ventas: false, offset: 0 }));
    expect(toggle).toHaveAttribute('aria-checked', 'false');
  });

  it('"Limpiar filtros" turns "Solo con ventas" back on', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    await userEvent.click(screen.getByRole('switch', { name: /Solo con ventas en el período/ }));
    await waitFor(() => expect(lastBoardParams().solo_con_ventas).toBe(false));

    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));

    await waitFor(() => expect(lastBoardParams().solo_con_ventas).toBe(true));
    expect(screen.getByRole('switch', { name: /Solo con ventas en el período/ })).toHaveAttribute('aria-checked', 'true');
  });

  it('the nested publications carry the toggle too', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    await userEvent.click(screen.getByRole('switch', { name: /Solo con ventas en el período/ }));
    await waitFor(() => expect(lastBoardParams().solo_con_ventas).toBe(false));

    await userEvent.click(screen.getByRole('button', { name: /Ver publicaciones de Impresora Multifunción Epson/ }));

    await waitFor(() => {
      const call = api.get.mock.calls.find(([url]) => url === '/ml-metricas/board/products/4101/publications');
      expect(call[1].params.solo_con_ventas).toBe(false);
    });
  });

  it('stock chips show their counts, include on the first click and hide on the second', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    const group = screen.getByRole('group', { name: 'Filtrar por stock' });
    expect(within(group).getByRole('button', { name: /^Sin stock/ })).toHaveTextContent('61');
    expect(within(group).getByRole('button', { name: /^Con stock/ })).toHaveTextContent('402');
    expect(within(group).getByRole('button', { name: /^Sin dato/ })).toHaveTextContent('8');

    await userEvent.click(within(group).getByRole('button', { name: /^Sin stock/ }));
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ stock: 'sin_stock', offset: 0 }));
    await userEvent.click(within(group).getByRole('button', { name: /Sin stock/ }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ stock_exclude: 'sin_stock' }));
    expect(lastBoardParams()).not.toHaveProperty('stock');
  });

  it('"Limpiar filtros" clears the stock chips', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    const group = screen.getByRole('group', { name: 'Filtrar por stock' });
    await userEvent.click(within(group).getByRole('button', { name: /^Con stock/ }));
    await waitFor(() => expect(lastBoardParams().stock).toBe('con_stock'));

    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));

    await waitFor(() => expect(lastBoardParams()).not.toHaveProperty('stock'));
    expect(within(group).getByRole('button', { name: /^Con stock/ })).toHaveAttribute('data-state', 'neutral');
  });

  it('the Stock column shows the row stock, "—" when unknown, and is no longer "coming soon"', async () => {
    await renderWithRouter(<MetricasML />);
    const epson = (await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro')).closest('tr');
    const lenovo = screen.getByText('Notebook Lenovo V15 G4 AMN Ryzen 5 8GB 256GB SSD').closest('tr');

    expect(epson.querySelector('td[data-col-id="stock"]')).toHaveTextContent('128');
    expect(lenovo.querySelector('td[data-col-id="stock"]')).toHaveTextContent('—');
    const header = screen.getByRole('columnheader', { name: /^Stock/ });
    expect(header.className).not.toMatch(/soonCol/);
  });

  it('ageing chips show the KPI buckets with counts and reach the request', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    const group = screen.getByRole('group', { name: 'Filtrar por ageing' });
    expect(within(group).getByRole('button', { name: /^Hasta 30 d/ })).toHaveTextContent('402');
    expect(within(group).getByRole('button', { name: /^31 a 60 d/ })).toHaveTextContent('46');
    expect(within(group).getByRole('button', { name: /^Más de 60 d/ })).toHaveTextContent('23');

    await userEvent.click(within(group).getByRole('button', { name: /^Más de 60 d/ }));
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ ageing: 'over_60', offset: 0 }));
    await userEvent.click(within(group).getByRole('button', { name: /Más de 60 d/ }));

    await waitFor(() => expect(lastBoardParams()).toMatchObject({ ageing_exclude: 'over_60' }));
    expect(lastBoardParams()).not.toHaveProperty('ageing');
  });

  it('an ageing chip with "Solo con ventas" on warns next to the toggle, and never flips it', async () => {
    const hint = () => screen.queryByText('Ocultando productos sin ventas en el período');
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    expect(hint()).not.toBeInTheDocument();
    const group = screen.getByRole('group', { name: 'Filtrar por ageing' });

    await userEvent.click(within(group).getByRole('button', { name: /^Más de 60 d/ }));

    expect(hint()).toBeInTheDocument();
    const toggle = screen.getByRole('switch', { name: /Solo con ventas en el período/ });
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ ageing: 'over_60', solo_con_ventas: true }));

    await userEvent.click(toggle);

    expect(hint()).not.toBeInTheDocument();
  });

  it('"Limpiar filtros" clears the ageing chips (and the warning with them)', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    const group = screen.getByRole('group', { name: 'Filtrar por ageing' });
    await userEvent.click(within(group).getByRole('button', { name: /^31 a 60 d/ }));
    await waitFor(() => expect(lastBoardParams().ageing).toBe('from_31_to_60'));

    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));

    await waitFor(() => expect(lastBoardParams()).not.toHaveProperty('ageing'));
    expect(screen.queryByText('Ocultando productos sin ventas en el período')).not.toBeInTheDocument();
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

describe('MetricasML publications sub-rows', () => {
  const PUBS_URL = '/ml-metricas/board/products/4101/publications';
  const pubCalls = () => api.get.mock.calls.filter(([url]) => url === PUBS_URL);
  const expandButton = () => screen.getByRole('button', { name: /publicaciones de Impresora Multifunción Epson/ });

  it('a late answer for the previous filters is never shown or reused', async () => {
    let resolveOld;
    const stale = { rows: [{ ...EPSON_PUBLICATIONS.rows[0], key: 'MLA_STALE', mla: 'MLA_STALE' }] };
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-metricas/board') return Promise.resolve({ data: BOARD_RESPONSE });
      if (url === PUBS_URL) {
        if (!config.params.stores) return new Promise((resolve) => (resolveOld = resolve));
        return Promise.resolve({ data: EPSON_PUBLICATIONS });
      }
      if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    });
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    await userEvent.click(expandButton());
    await waitFor(() => expect(pubCalls()).toHaveLength(1));

    // The filters change while the old sub-rows are still on their way.
    await userEvent.click(
      within(screen.getByRole('group', { name: 'Filtrar por tienda oficial' })).getByRole('button', { name: /Gauss/ }),
    );
    await waitFor(() => expect(lastBoardParams().stores).toBe('57997'));
    resolveOld({ data: stale });
    await new Promise((r) => setTimeout(r, 0));

    await userEvent.click(expandButton());

    expect(await screen.findByText('MLA2060835678')).toBeInTheDocument();
    expect(screen.queryByText('MLA_STALE')).not.toBeInTheDocument();
    expect(pubCalls()).toHaveLength(2);
    expect(pubCalls()[1][1].params.stores).toBe('57997');
  });

  it('a failed load is not cached: collapsing and expanding again retries', async () => {
    let fail = true;
    api.get.mockImplementation((url) => {
      if (url === '/ml-metricas/board') return Promise.resolve({ data: BOARD_RESPONSE });
      if (url === PUBS_URL) return fail ? Promise.reject(new Error('boom')) : Promise.resolve({ data: EPSON_PUBLICATIONS });
      if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    });
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');

    await userEvent.click(expandButton());
    expect(await screen.findByText('No se pudieron cargar las publicaciones.')).toBeInTheDocument();

    fail = false;
    await userEvent.click(expandButton()); // collapse
    await userEvent.click(expandButton()); // expand again

    expect(await screen.findByText('MLA2060835678')).toBeInTheDocument();
    expect(pubCalls()).toHaveLength(2);
  });
});

describe('MetricasML period limit', () => {
  it('a custom range over a year is flagged next to the range and never requested', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
    const before = boardCalls().length;

    await userEvent.click(screen.getByTitle('Seleccionar rango personalizado'));
    const desde = screen.getByLabelText('Desde');
    const hasta = screen.getByLabelText('Hasta');
    await userEvent.clear(desde);
    await userEvent.type(desde, '2025-01-01');
    await userEvent.clear(hasta);
    await userEvent.type(hasta, '2026-01-02');

    expect(await screen.findByRole('alert')).toHaveTextContent('El período máximo es de 1 año');
    const aplicar = screen.getByRole('button', { name: 'Aplicar' });
    expect(aplicar).toBeDisabled();
    await userEvent.click(aplicar);
    expect(boardCalls().length).toBe(before);
    expect(boardCalls().some(([, config]) => config.params.date_from === '2025-01-01')).toBe(false);
  });

  it('a 422 from the board shows the backend message, not the generic error', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/ml-metricas/board') {
        return Promise.reject({
          response: {
            status: 422,
            data: { error: { code: 'HTTP_422', message: 'El período no puede superar 366 días' } },
          },
        });
      }
      if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    });
    await renderWithRouter(<MetricasML />);

    expect(await screen.findByText(/El período no puede superar 366 días/)).toBeInTheDocument();
    expect(screen.queryByText(/Error al cargar las métricas/)).not.toBeInTheDocument();
  });
});
