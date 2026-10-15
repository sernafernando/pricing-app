/**
 * What the Métricas ML page shows when the board answers with ads subtracted
 * (`kpis.ads` present): the banner, the adjusted cards and the ads column.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
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

const withAds = (ads, rowAds = { cost: 410200 }) => ({
  ...BOARD_RESPONSE,
  kpis: { ...BOARD_RESPONSE.kpis, ads },
  rows: BOARD_RESPONSE.rows.map((row, index) => (index === 0 && ads ? { ...row, ads: rowAds } : row)),
});

const answerWith = (board) => {
  api.get.mockReset();
  api.get.mockImplementation((url) => Promise.resolve({ data: url === '/ml-metricas/board' ? board : {} }));
};

beforeEach(() => {
  seedTiendasOficiales();
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

describe('MetricasML with ads subtracted', () => {
  it('shows nothing about ads while the board carries no ads block', async () => {
    answerWith(BOARD_RESPONSE);
    await renderWithRouter(<MetricasML />);
    await screen.findByText(/Impresora Multifunción Epson EcoTank/);
    expect(screen.queryByText(/Publicidad restada/)).not.toBeInTheDocument();
    expect(screen.queryByText('Ajustado')).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Publicidad/ })).not.toBeInTheDocument();
  });

  it('shows the banner, the adjusted cards and the ads column', async () => {
    answerWith(withAds(ADS_KPIS));
    await renderWithRouter(<MetricasML />);

    expect(await screen.findByRole('status')).toHaveTextContent('Publicidad restada: $ 17.516.239,51');
    expect(screen.getAllByText('Ajustado')).toHaveLength(2);
    expect(screen.getByRole('columnheader', { name: /Publicidad \(inversión\)/ })).toBeInTheDocument();
    expect(screen.getByText('$ 410.200,00')).toBeInTheDocument();
  });

  it('explains a "todo" that filters downgraded to "mla"', async () => {
    answerWith(withAds({ ...ADS_KPIS, requested: 'todo', applied: 'mla' }));
    await renderWithRouter(<MetricasML />);

    expect(await screen.findByText('Con filtros solo se restan los Ads de publicaciones')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Aplicado: Ads de publicaciones')).toBeInTheDocument());
  });
});
