/**
 * Métricas ML: the daily chart "Ventas por día" (audit B10, the old dashboard's bars) reads the same board answer
 * as the KPI strip, so it follows every filter without a request of its own.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE } from '../test/visual/metricasMlFixtures';
import { seedTiendasOficiales } from '../test/tiendasOficialesFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const OPS = BOARD_RESPONSE.kpis.gross.series.map((_, i) => i + 1);
const board = { ...BOARD_RESPONSE, kpis: { ...BOARD_RESPONSE.kpis, operations: { series: OPS } } };

beforeEach(() => {
  seedTiendasOficiales();
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/ml-metricas/board') return Promise.resolve({ data: board });
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

describe('MetricasML page — Ventas por día', () => {
  it("shows the board's last 14 days with their operations, from the same board request", async () => {
    await renderWithRouter(<MetricasML />);

    const lista = await screen.findByRole('list', { name: 'Ventas por día' });
    const dias = within(lista).getAllByRole('listitem');
    expect(dias).toHaveLength(14);
    expect(within(dias[13]).getByText(`${OPS.at(-1)} ops`)).toBeInTheDocument();
    expect(api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board')).toHaveLength(1);
  });
});
