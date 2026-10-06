import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import DashboardMetricasML from './DashboardMetricasML';
import api from '../services/api';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

beforeEach(() => {
  seedTiendasOficiales([
    { store_id: 57997, nombre: 'Gauss', clave: null, orden: 0, activa: true },
    { store_id: 2645, nombre: 'TP-Link vieja', clave: 'tplink', orden: 1, activa: false },
    { store_id: 471846, nombre: 'TP-Link', clave: 'tplink', orden: 2, activa: true },
  ]);
  api.get.mockReset();
  api.get.mockImplementation((url) =>
    Promise.resolve({ data: url.includes('disponibles') || url.includes('/usuarios/pms') || url.includes('por-') ? [] : {} }),
  );
});

afterAll(resetTiendasOficiales);

describe('DashboardMetricasML official store filter', () => {
  it('stores sharing a clave are ONE checkbox that selects every id', async () => {
    await renderWithRouter(<DashboardMetricasML />);

    expect(await screen.findAllByRole('checkbox', { name: 'TP-Link' })).toHaveLength(1);
    expect(screen.queryByRole('checkbox', { name: 'TP-Link vieja' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'TP-Link' }));

    await waitFor(() => {
      const conTiendas = api.get.mock.calls.filter(([, c]) => c?.params?.tiendas_oficiales === '2645,471846');
      expect(conTiendas.length).toBeGreaterThan(0);
    });
    expect(screen.getByRole('checkbox', { name: 'TP-Link' })).toBeChecked();
  });
});
