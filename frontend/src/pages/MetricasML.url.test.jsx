/**
 * metricas-ml-tablero U1 (audit B3): the filters live in the URL, so a reload keeps the view and a filtered view
 * can be bookmarked or shared.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
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

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board');

function LocationProbe() {
  return <output data-testid="location">{useLocation().search}</output>;
}

const renderAt = (search) =>
  renderWithRouter(
    <>
      <MetricasML />
      <LocationProbe />
    </>,
    { initialEntries: [`/metricas-ml${search}`] },
  );

describe('MetricasML: filters in the URL', () => {
  it('opens the view a link describes: period, grouping, filters and sort', async () => {
    await renderAt('?periodo=custom&desde=2026-09-01&hasta=2026-09-15&agrupar=publication&marcas=Epson&tienda=57997&solo_ventas=0&orden=units_30d&dir=asc');

    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    // The FIRST request already asks for it: no request with the defaults first.
    expect(boardCalls()[0][1].params).toMatchObject({
      date_from: '2026-09-01',
      date_to: '2026-09-15',
      group_by: 'publication',
      marcas: 'Epson',
      stores: '57997',
      solo_con_ventas: false,
      sort: 'units_30d',
      sort_dir: 'asc',
    });
  });

  it('writes a changed filter into the URL, and "Limpiar filtros" takes it out', async () => {
    await renderAt('');
    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(screen.getByTestId('location')).toHaveTextContent(/^$/);

    await userEvent.click(screen.getByRole('switch', { name: /Solo con ventas en el período/ }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('?solo_ventas=0'));

    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^$/));
  });
});
