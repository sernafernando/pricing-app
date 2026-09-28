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

  it('picking a product filter returns to page 1, like every other filter', async () => {
    // Changing WHAT is filtered must reset WHERE you are in the result set.
    // Without it, picking a brand while on page 3 renders "no hay ventas que
    // coincidan" for a brand that DOES have sales -- they are on page 1, and
    // nothing on screen says so.
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.resolve({
          data: { sales: [], total: 300, limit: 50, offset: 0, facets: {} },
        });
      }
      if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    });

    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('Marca')).toBeInTheDocument());

    // Actually navigate away from page 1. `?offset=` in the URL does NOT work
    // here: this screen never read pagination from the URL, so seeding it that
    // way leaves the page on offset 0 and the assertion below passes for the
    // wrong reason (it did, before this comment existed).
    await userEvent.click(screen.getByText('Siguiente'));
    await waitFor(() => {
      const tras = api.get.mock.calls.filter(([url]) => url === '/ml-ventas-ops/sales').at(-1);
      expect(tras[1].params.offset).toBeGreaterThan(0);
    });

    await userEvent.click(screen.getByText('Marca'));
    await userEvent.click(await screen.findByText('Sony'));

    await waitFor(() => {
      const ultima = api.get.mock.calls
        .filter(([url]) => url === '/ml-ventas-ops/sales')
        .at(-1);
      // Assert BOTH: that the brand travelled AND that the offset reset. The
      // offset alone would also be 0 on the very first load, so it cannot
      // discriminate on its own.
      expect(ultima[1].params.marcas).toBe('Sony');
      expect(ultima[1].params.offset ?? 0).toBe(0);
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
