/**
 * Tests for the product filter trio (marca / subcategoría / PM) wired into
 * `VentasML.jsx` from the shared `ProductFiltersPanel` component
 * (`ventas-ml-filtros-producto`). Kept in a separate file from
 * `VentasML.test.jsx` — same page, new scope, no need to re-thread through
 * the huge existing test file.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import VentasML from './VentasML';
import api, { productosAPI } from '../services/api';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: () => true,
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

function mockAllEndpoints() {
  api.get.mockImplementation((url) => {
    if (url === '/ml-ventas-ops/sales') {
      return Promise.resolve({
        data: { sales: [], total: 0, limit: 50, offset: 0, facets: {} },
      });
    }
    if (url === '/usuarios/pms') {
      return Promise.resolve({ data: [] });
    }
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['Sony', 'LG'] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
}

beforeEach(() => {
  api.get.mockReset();
  productosAPI.marcas.mockReset();
  productosAPI.subcategorias.mockReset();
  mockAllEndpoints();
});

describe('Product filters (marca / subcategoría / PM) on VentasML', () => {
  it('sends the selected marca as `marcas` on GET /ml-ventas-ops/sales', async () => {
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('Marca')).toBeInTheDocument());

    await userEvent.click(screen.getByText('Marca'));
    const sonyOption = await screen.findByText('Sony');
    await userEvent.click(sonyOption);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/ml-ventas-ops/sales',
        expect.objectContaining({ params: expect.objectContaining({ marcas: 'Sony' }) }),
      );
    });
  });

  it('"Limpiar filtros" clears the selected marca too', async () => {
    await renderWithRouter(<VentasML />, { initialEntries: ['/?marcas=Sony'] });
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/ml-ventas-ops/sales',
        expect.objectContaining({ params: expect.objectContaining({ marcas: 'Sony' }) }),
      );
    });

    await userEvent.click(screen.getByText('Limpiar filtros'));

    await waitFor(() => {
      const lastSalesCall = api.get.mock.calls
        .filter(([url]) => url === '/ml-ventas-ops/sales')
        .at(-1);
      expect(lastSalesCall[1].params.marcas).toBeUndefined();
    });
  });
});
