/**
 * The prearmadas of a product (publicaciones-ml-paridad-productos S12b), as Productos shows them beside each product
 * (`PrearmadaBadge`, `POST /prearmados/stats/batch`): how many are ready, or else how many are available as an
 * upgrade. Only with `produccion.ver_prearmadas_stats`, as in Productos.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import ProductPrearmadas from './ProductPrearmadas';
import api from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    post: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  registerAuthFailureHandler: vi.fn(),
}));

let granted = new Set(['produccion.ver_prearmadas_stats']);
// Stable across renders, as the context's own `tienePermiso` is: the hook re-runs its read when it changes.
const tienePermiso = (permiso) => granted.has(permiso);
vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso }),
}));

const stats = (exact, upgrade) => ({ data: { stats: { 4101: { exact, upgrade } } } });

beforeEach(() => {
  granted = new Set(['produccion.ver_prearmadas_stats']);
  api.post.mockReset();
});

describe('the badge', () => {
  it("asks for this product's prearmadas and says how many are ready", async () => {
    api.post.mockResolvedValue(stats(2, 5));

    render(<ProductPrearmadas productItemId={4101} />);

    expect(await screen.findByText('2 listas')).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith('/prearmados/stats/batch', { items: [{ item_id: 4101 }] }, undefined);
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('with none ready, says how many are available as an upgrade', async () => {
    api.post.mockResolvedValue(stats(0, 1));

    render(<ProductPrearmadas productItemId={4101} />);

    expect(await screen.findByText('1 disponible (upgrade)')).toBeInTheDocument();
  });

  it('shows nothing when there are none', async () => {
    api.post.mockResolvedValue(stats(0, 0));

    const { container } = render(<ProductPrearmadas productItemId={4101} />);

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe('permission', () => {
  it('without produccion.ver_prearmadas_stats shows nothing and asks nothing', () => {
    granted = new Set();

    const { container } = render(<ProductPrearmadas productItemId={4101} />);

    expect(container).toBeEmptyDOMElement();
    expect(api.post).not.toHaveBeenCalled();
  });
});
