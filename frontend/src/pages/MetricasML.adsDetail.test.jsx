/**
 * The ads KPI block of the Métricas ML page: present with the toggle on, absent with it off.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE } from '../test/visual/metricasMlFixtures';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import { ADS_KPIS } from '../components/metricasMl/adsFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const withAds = (ads) => ({
  ...BOARD_RESPONSE,
  kpis: { ...BOARD_RESPONSE.kpis, ads },
});

let board;
beforeEach(() => {
  seedTiendasOficiales();
  board = BOARD_RESPONSE;
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') return Promise.resolve({ data: config?.params?.publicidad ? board : BOARD_RESPONSE });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});
afterAll(resetTiendasOficiales);

const pick = async (name) => userEvent.click(within(await screen.findByRole('group', { name: 'Publicidad' })).getByRole('button', { name }));

describe('MetricasML ads detail', () => {
  it('shows none of it with the toggle off', async () => {
    await renderWithRouter(<MetricasML />);
    await screen.findByText(/Impresora Multifunción Epson/);
    expect(screen.queryByRole('region', { name: 'Publicidad (ML Ads)' })).not.toBeInTheDocument();
  });

  it('shows the KPI block and its coverage note with the position on', async () => {
    board = withAds(ADS_KPIS);
    await renderWithRouter(<MetricasML />);
    await pick('Restar Ads de publicaciones');
    expect(await screen.findByRole('region', { name: 'Publicidad (ML Ads)' })).toBeInTheDocument();
    expect(screen.getByText('Datos de Ads hasta el 13/10')).toBeInTheDocument();
  });
});
