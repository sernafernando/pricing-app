/**
 * The board opens on the current month in Argentina time (like Ventas ML),
 * and "Limpiar filtros" goes back to that month.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
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

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board');
const lastBoardParams = () => boardCalls().at(-1)[1].params;

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

afterEach(() => {
  vi.useRealTimers();
  resetTiendasOficiales();
});

describe('MetricasML default period', () => {
  it('opens on the current month', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-14T15:00:00Z'));

    renderWithRouter(<MetricasML />);

    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(lastBoardParams()).toMatchObject({ date_from: '2026-10-01', date_to: '2026-10-14' });
  });

  it('uses the Argentina day, not the UTC day, near midnight', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    // 22:00 on Oct 31 in Argentina is already Nov 1 in UTC.
    vi.setSystemTime(new Date('2026-11-01T01:00:00Z'));

    renderWithRouter(<MetricasML />);

    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(lastBoardParams()).toMatchObject({ date_from: '2026-10-01', date_to: '2026-10-31' });
  });

  it('"Limpiar filtros" goes back to the current month', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-14T15:00:00Z'));
    renderWithRouter(<MetricasML />);
    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));

    await userEvent.click(screen.getByRole('button', { name: '7d' }));
    await waitFor(() => expect(lastBoardParams().date_from).not.toBe('2026-10-01'));

    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));
    await waitFor(() =>
      expect(lastBoardParams()).toMatchObject({ date_from: '2026-10-01', date_to: '2026-10-14' }),
    );
  });
});
