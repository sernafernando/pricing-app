import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import Tienda from './Tienda';
import api, { productosAPI } from '../services/api';

// Live color sync is not exercised here; stub the subscription so the page renders without an SSEProvider.
vi.mock('../hooks/useSSEChannel', () => ({ useSSEChannel: vi.fn() }));

function setupApiMocks(productos) {
  productosAPI.listarTienda.mockResolvedValue({ data: { productos, total: productos.length } });
  productosAPI.statsDinamicos.mockResolvedValue({ data: {} });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
  api.get.mockImplementation((url) => {
    if (url === '/tipo-cambio/actual') return Promise.resolve({ data: { compra: 1000, venta: 1000 } });
    if (url.startsWith('/auditoria') || url.startsWith('/usuarios/pms')) return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
}

describe('per-product instalment config', () => {
  it('shows a saved 0 extra markup as 0 and saves it back as 0, not null', async () => {
    setupApiMocks([
      { item_id: 'Z1', codigo: 'SKU001', descripcion: 'Producto Test', marca: 'BRAND_X', stock: 5, moneda_costo: 'USD', costo: 10, recalcular_cuotas_auto: null, markup_adicional_cuotas_custom: 0 },
    ]);
    api.patch.mockResolvedValue({ data: {} });
    const user = userEvent.setup();

    await act(async () => {
      renderWithRouter(<Tienda />);
    });
    await waitFor(() => expect(screen.getByText('Producto Test')).toBeInTheDocument());

    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Configuración de cuotas' }));
    });

    expect(screen.getByPlaceholderText('Dejar vacío para usar configuración global')).toHaveValue(0);

    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Guardar' }));
    });

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/productos/Z1/config-cuotas', expect.objectContaining({ markup_adicional_cuotas_custom: 0 }));
    });
  });
});
