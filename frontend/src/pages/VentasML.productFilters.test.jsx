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

// What the server answers for the product option lists: each one narrowed by
// the OTHER active filters (here: a brand, a category), never by its own.
const PRODUCT_OPTIONS = {
  marcas: ['Sony', 'LG'],
  categorias: ['Audio', 'Video'],
  subcategorias: [
    { nombre: 'Audio', subcategorias: [{ id: 3, nombre: 'Parlantes' }] },
    { nombre: 'Video', subcategorias: [{ id: 7, nombre: 'Televisores' }] },
  ],
  pms: [{ id: 10, nombre: 'Ana' }],
};
const SONY_OPTIONS = {
  marcas: ['Sony', 'LG'],
  categorias: ['Audio'],
  subcategorias: [{ nombre: 'Audio', subcategorias: [{ id: 3, nombre: 'Parlantes' }] }],
  pms: [{ id: 10, nombre: 'Ana' }],
};

function salesResponse(params = {}, total = 0) {
  const product = params.marcas === 'Sony' ? SONY_OPTIONS : PRODUCT_OPTIONS;
  return { data: { sales: [], total, limit: 50, offset: 0, facets: { product } } };
}

function mockAllEndpoints() {
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-ventas-ops/sales') return Promise.resolve(salesResponse(config?.params));
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  api.get.mockReset();
  productosAPI.marcas.mockReset();
  productosAPI.subcategorias.mockReset();
  mockAllEndpoints();
});

describe('Product filters (marca / categoría / subcategoría / PM) on VentasML', () => {
  it('offers the lists the sales response carries, loading none of its own', async () => {
    await renderWithRouter(<VentasML />);
    await userEvent.click(await screen.findByRole('button', { name: 'Categoría' }));

    expect(await screen.findByText('Video')).toBeInTheDocument();
    expect(productosAPI.marcas).not.toHaveBeenCalled();
    expect(productosAPI.subcategorias).not.toHaveBeenCalled();
    expect(api.get).not.toHaveBeenCalledWith('/usuarios/pms', expect.anything());
  });

  it('sends the selected categoría as `categorias` on GET /ml-ventas-ops/sales', async () => {
    await renderWithRouter(<VentasML />);
    await userEvent.click(await screen.findByRole('button', { name: 'Categoría' }));
    await userEvent.click(await screen.findByText('Audio'));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/ml-ventas-ops/sales',
        expect.objectContaining({ params: expect.objectContaining({ categorias: 'Audio' }) }),
      );
    });
  });

  it('picking a brand narrows the categories and subcategories offered next', async () => {
    await renderWithRouter(<VentasML />);
    await userEvent.click(await screen.findByRole('button', { name: 'Marca' }));
    await userEvent.click(await screen.findByText('Sony'));

    await userEvent.click(await screen.findByRole('button', { name: /Categoría/ }));
    expect(await screen.findByText('Audio')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Video')).not.toBeInTheDocument());
  });

  it('sends the selected marca as `marcas` on GET /ml-ventas-ops/sales', async () => {
    await renderWithRouter(<VentasML />);
    await userEvent.click(await screen.findByRole('button', { name: 'Marca' }));
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
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-ventas-ops/sales') return Promise.resolve(salesResponse(config?.params, 300));
      if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    });

    await renderWithRouter(<VentasML />);
    await screen.findByRole('button', { name: 'Marca' });

    // Actually navigate away from page 1. `?offset=` in the URL does NOT work
    // here: this screen never read pagination from the URL, so seeding it that
    // way leaves the page on offset 0 and the assertion below passes for the
    // wrong reason (it did, before this comment existed).
    await userEvent.click(screen.getByText('Siguiente'));
    await waitFor(() => {
      const tras = api.get.mock.calls.filter(([url]) => url === '/ml-ventas-ops/sales').at(-1);
      expect(tras[1].params.offset).toBeGreaterThan(0);
    });

    await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
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
