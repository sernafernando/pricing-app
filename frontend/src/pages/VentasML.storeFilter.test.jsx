/**
 * ODD `metricas-ml-tablero` T1: the "Tienda:" chip row on Ventas ML. Counts
 * come from `facets.stores`; clicking a chip sends `stores` to the list AND
 * the KPI strip (one shared params builder).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import VentasML from './VentasML';
import api, { productosAPI } from '../services/api';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const FACETS = {
  operation_status: {},
  goods_status: {},
  operation_status_total: 9,
  goods_status_total: 9,
  alerts_total: 0,
  stores: { 57997: 5, 2645: 3, sin_tienda: 2 },
  stores_total: 9,
};

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/ml-ventas-ops/sales') {
      return Promise.resolve({ data: { sales: [], total: 9, limit: 50, offset: 0, facets: FACETS } });
    }
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

function lastParams(url) {
  return api.get.mock.calls.filter(([u]) => u === url).at(-1)[1].params;
}

describe('Tienda filter on VentasML', () => {
  it('renders one chip per store with its facet count', async () => {
    await renderWithRouter(<VentasML />);
    const group = await screen.findByRole('group', { name: 'Filtrar por tienda oficial' });
    await waitFor(() => expect(within(group).getByRole('button', { name: 'Gauss · 5' })).toBeInTheDocument());
    expect(within(group).getByRole('button', { name: 'Todas · 9' })).toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'TP-Link Oficial · 3' })).toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'Forza/Verbatim · 0' })).toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'Multimarca · 0' })).toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'Sin tienda · 2' })).toBeInTheDocument();
  });

  it('clicking a store sends `stores` to the list and the KPI strip', async () => {
    await renderWithRouter(<VentasML />);
    const group = await screen.findByRole('group', { name: 'Filtrar por tienda oficial' });
    await userEvent.click(await within(group).findByRole('button', { name: /TP-Link Oficial/ }));

    await waitFor(() => {
      expect(lastParams('/ml-ventas-ops/sales').stores).toBe('2645');
      expect(lastParams('/ml-ventas-ops/sales/kpis').stores).toBe('2645');
    });
    expect(lastParams('/ml-ventas-ops/sales').offset ?? 0).toBe(0);
  });

  it('"Limpiar filtros" clears the store', async () => {
    await renderWithRouter(<VentasML />);
    const group = await screen.findByRole('group', { name: 'Filtrar por tienda oficial' });
    await userEvent.click(await within(group).findByRole('button', { name: /Gauss/ }));
    await waitFor(() => expect(lastParams('/ml-ventas-ops/sales').stores).toBe('57997'));

    await userEvent.click(screen.getByText('Limpiar filtros'));

    await waitFor(() => expect(lastParams('/ml-ventas-ops/sales').stores).toBeUndefined());
  });
});

describe('Tienda chips follow the facet buckets', () => {
  it('a store outside the known list gets its own selectable chip, and the chips add up to Todas', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.resolve({
          data: {
            sales: [],
            total: 10,
            limit: 50,
            offset: 0,
            facets: { ...FACETS, stores: { 57997: 5, 2645: 2, 777123: 1, sin_tienda: 2 }, stores_total: 10 },
          },
        });
      }
      if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    });
    await renderWithRouter(<VentasML />);
    const group = await screen.findByRole('group', { name: 'Filtrar por tienda oficial' });
    const unknown = await within(group).findByRole('button', { name: 'Tienda 777123 · 1' });

    const counts = within(group)
      .getAllByRole('button')
      .filter((b) => !b.textContent.startsWith('Todas'))
      .map((b) => Number(b.textContent.split('·').pop().trim()));
    expect(counts.reduce((a, b) => a + b, 0)).toBe(10);

    await userEvent.click(unknown);
    await waitFor(() => expect(lastParams('/ml-ventas-ops/sales').stores).toBe('777123'));
  });
});
