/**
 * Tests for the "Anomalías" tab added to ItemsSinMLA.jsx
 * (productos-catalog-family-tree closing slice).
 *
 * Scope:
 *   - Tab button gated by admin.ver_anomalias_vinculadas
 *   - Loads GET /items-sin-mla/anomalias-vinculadas when the tab is opened
 *   - Renders anomaly rows with the cross_item/unresolvable reason badge
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import ItemsSinMLA from './ItemsSinMLA';
import api from '../services/api';

const mockTienePermiso = vi.fn(() => true);

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => mockTienePermiso(codigo),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const ANOMALIAS_FIXTURE = [
  {
    mla: 'MLA2068711536',
    item_id: 2905,
    codigo: 'COD2905',
    descripcion: 'Producto fuente',
    marca: 'MarcaX',
    permalink: 'https://mercadolibre.com.ar/MLA2068711536',
    related_mla: 'MLA1493337181',
    related_item_id: 3271,
    reason: 'cross_item',
    stock_relation: 1,
  },
  {
    mla: 'MLA2374249178',
    item_id: 100,
    codigo: 'COD100',
    descripcion: 'Otro producto',
    marca: 'MarcaZ',
    permalink: null,
    related_mla: 'MLA3100873948',
    related_item_id: null,
    reason: 'unresolvable',
    stock_relation: 1,
  },
];

function setupBaseApiMocks() {
  api.get.mockImplementation((url) => {
    if (url === '/items-sin-mla/listas-precios') return Promise.resolve({ data: [] });
    if (url === '/items-sin-mla/tiendas-oficiales') return Promise.resolve({ data: [] });
    if (url === '/items-sin-mla/items-sin-mla') return Promise.resolve({ data: [] });
    if (url === '/asignaciones/items-sin-mla') return Promise.resolve({ data: [] });
    if (url === '/asignaciones/usuarios-asignables') return Promise.resolve({ data: [] });
    if (url === '/items-sin-mla/anomalias-vinculadas') return Promise.resolve({ data: ANOMALIAS_FIXTURE });
    return Promise.resolve({ data: [] });
  });
}

beforeEach(() => {
  mockTienePermiso.mockReset();
  mockTienePermiso.mockImplementation(() => true);
  setupBaseApiMocks();
});

describe('Anomalías tab visibility', () => {
  it('shows the "Anomalías" tab when admin.ver_anomalias_vinculadas is granted', async () => {
    await renderWithRouter(<ItemsSinMLA />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Anomal[íi]as/i })).toBeInTheDocument();
    });
  });

  it('hides the "Anomalías" tab when admin.ver_anomalias_vinculadas is not granted', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'admin.ver_anomalias_vinculadas');

    await renderWithRouter(<ItemsSinMLA />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Sin MLA/i })).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /Anomal[íi]as/i })).not.toBeInTheDocument();
  });
});

describe('Anomalías tab data loading and rendering', () => {
  it('loads and renders anomalies with reason badges when the tab is opened', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<ItemsSinMLA />);

    const tabButton = await screen.findByRole('button', { name: /Anomal[íi]as/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/items-sin-mla/anomalias-vinculadas');
    });

    expect(await screen.findByText('MLA2068711536')).toBeInTheDocument();
    expect(screen.getByText('MLA1493337181')).toBeInTheDocument();
    expect(screen.getByText('Cross-item')).toBeInTheDocument();
    expect(screen.getByText('Irresoluble')).toBeInTheDocument();
    expect(screen.getByText('COD2905')).toBeInTheDocument();
  });

  it('shows an empty state when there are no anomalies', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/items-sin-mla/anomalias-vinculadas') return Promise.resolve({ data: [] });
      if (url === '/items-sin-mla/listas-precios') return Promise.resolve({ data: [] });
      if (url === '/items-sin-mla/tiendas-oficiales') return Promise.resolve({ data: [] });
      if (url === '/items-sin-mla/items-sin-mla') return Promise.resolve({ data: [] });
      if (url === '/asignaciones/items-sin-mla') return Promise.resolve({ data: [] });
      if (url === '/asignaciones/usuarios-asignables') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });

    const user = userEvent.setup();
    await renderWithRouter(<ItemsSinMLA />);

    const tabButton = await screen.findByRole('button', { name: /Anomal[íi]as/i });
    await user.click(tabButton);

    expect(await screen.findByText(/No se encontraron anomalías/i)).toBeInTheDocument();
  });
});
