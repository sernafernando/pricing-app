/**
 * The listing type order on Métricas ML (owner, 2026-11-02): Clásica first, then 3, 6, 9 and 12 cuotas. The page
 * opens by product (owner: "abrilo en productos"); the view by publication starts ordered by type, and a sort the
 * user picked survives the switch.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE } from '../test/visual/metricasMlFixtures';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

beforeEach(() => {
  seedTiendasOficiales();
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/ml-metricas/board') return Promise.resolve({ data: BOARD_RESPONSE });
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

const lastBoardParams = () =>
  api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board').at(-1)[1].params;

async function openBoard() {
  await renderWithRouter(<MetricasML />);
  await screen.findByText('Impresora Multifunción Epson EcoTank L3250 Color Negro');
  return screen.getByRole('group', { name: 'Agrupar por' });
}

describe('Métricas ML: the listing type order', () => {
  it('opens by product, by gross, and the view by publication asks for the type order', async () => {
    const views = await openBoard();
    expect(lastBoardParams()).toMatchObject({ group_by: 'product', sort: 'gross', sort_dir: 'desc' });

    await userEvent.click(within(views).getByRole('button', { name: 'Publicación' }));
    await waitFor(() =>
      expect(lastBoardParams()).toMatchObject({ group_by: 'publication', sort: 'listing_kind', sort_dir: 'asc' }),
    );

    await userEvent.click(within(views).getByRole('button', { name: 'Producto' }));
    await waitFor(() => expect(lastBoardParams()).toMatchObject({ group_by: 'product', sort: 'gross', sort_dir: 'desc' }));
  });
});
