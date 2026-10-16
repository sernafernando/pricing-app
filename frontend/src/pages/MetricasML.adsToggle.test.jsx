/**
 * The ads toggle on the Métricas ML page: what it asks the board for, what it
 * shows with the answer, and who gets to see it (`ml_metricas.ver_ganancia`).
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE } from '../test/visual/metricasMlFixtures';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import { ADS_KPIS } from '../components/metricasMl/adsFixtures';

let granted = ['ml_metricas.ver', 'ml_metricas.ver_ganancia'];
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: (code) => granted.includes(code), cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../utils/ventasMlExport', async (importOriginal) => ({
  ...(await importOriginal()),
  exportMetricasCsv: vi.fn().mockResolvedValue(undefined),
}));
const { exportMetricasCsv } = await import('../utils/ventasMlExport');

const withAds = (ads, rowAds = { cost: 410200 }) => ({
  ...BOARD_RESPONSE,
  kpis: { ...BOARD_RESPONSE.kpis, ads },
  rows: BOARD_RESPONSE.rows.map((row, index) => (index === 0 && ads ? { ...row, ads: rowAds } : row)),
});

let board;

beforeEach(() => {
  seedTiendasOficiales();
  granted = ['ml_metricas.ver', 'ml_metricas.ver_ganancia'];
  board = BOARD_RESPONSE;
  exportMetricasCsv.mockClear();
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') return Promise.resolve({ data: config?.params?.publicidad ? board : BOARD_RESPONSE });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board');
const lastBoardParams = () => boardCalls().at(-1)[1].params;
const control = () => screen.findByRole('group', { name: 'Publicidad' });

describe('MetricasML ads toggle', () => {
  it('starts at "Sin publicidad" and asks for no ads', async () => {
    await renderWithRouter(<MetricasML />);
    const group = await control();
    expect(within(group).getByRole('button', { name: 'Sin publicidad' })).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(lastBoardParams()).not.toHaveProperty('publicidad');
    expect(screen.queryByText(/Publicidad restada/)).not.toBeInTheDocument();
  });

  it('asks the board for the chosen position and shows the banner, the adjusted cards and the ads column', async () => {
    board = withAds(ADS_KPIS);
    await renderWithRouter(<MetricasML />);
    await userEvent.click(within(await control()).getByRole('button', { name: 'Restar Ads de publicaciones' }));

    await waitFor(() => expect(lastBoardParams().publicidad).toBe('mla'));
    expect(await screen.findByRole('status')).toHaveTextContent('Publicidad restada: $ 17.516.239,51');
    expect(screen.getAllByText('Ajustado')).toHaveLength(2);
    expect(screen.getByRole('columnheader', { name: /Publicidad \(inversión\)/ })).toBeInTheDocument();
    expect(screen.getByText('$ 410.200,00')).toBeInTheDocument();
  });

  it('keeps the CSV as it is today: the export never carries the position', async () => {
    board = withAds(ADS_KPIS);
    await renderWithRouter(<MetricasML />);
    await userEvent.click(within(await control()).getByRole('button', { name: 'Restar toda la publicidad' }));
    await waitFor(() => expect(lastBoardParams().publicidad).toBe('todo'));

    await userEvent.click(screen.getByRole('button', { name: /Exportar CSV/ }));
    await waitFor(() => expect(exportMetricasCsv).toHaveBeenCalled());
    expect(exportMetricasCsv.mock.calls[0][0]).not.toHaveProperty('publicidad');
  });

  it('hides the control without ver_ganancia, and never asks for ads', async () => {
    granted = ['ml_metricas.ver'];
    await renderWithRouter(<MetricasML />);
    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(screen.queryByRole('group', { name: 'Publicidad' })).not.toBeInTheDocument();
    expect(lastBoardParams()).not.toHaveProperty('publicidad');
  });
});
