/**
 * PR2 — AppLayout stacks unread compras.* banners; OK → PATCH /ok (DESCARTADA).
 * No localStorage dismiss for these banners (persistent).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import api from '../services/api';
import AppLayout from './AppLayout';

vi.mock('./Sidebar', () => ({
  default: () => <div data-testid="sidebar" />,
}));

vi.mock('./TopBar', () => ({
  default: () => <div data-testid="topbar" />,
}));

const sseStub = { isDegraded: () => false, subscribe: () => () => {} };
vi.mock('../contexts/SSEContext', () => ({
  SSEProvider: ({ children }) => children,
  useSSE: () => sseStub,
}));

vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: () => {},
}));

const facturaNotif = {
  id: 11,
  tipo: 'compras.factura_cargada',
  estado: 'PENDIENTE',
  mensaje: 'Factura FA-99 cargada en P-01-2026-00012 (Acme). Revisá el pedido en Compras.',
  item_id: 42,
  leida: false,
};

const markupNotif = {
  id: 99,
  tipo: 'markup_bajo',
  estado: 'PENDIENTE',
  mensaje: 'Markup bajo',
  item_id: 1,
  leida: false,
};

describe('AppLayout — compras banners', () => {
  beforeEach(() => {
    api.get.mockImplementation((url) => {
      if (url === '/notificaciones') {
        return Promise.resolve({ data: [facturaNotif, markupNotif] });
      }
      if (url === '/alertas/activas') {
        return Promise.resolve({ data: [] });
      }
      if (url === '/alertas/configuracion') {
        return Promise.resolve({ data: { max_alertas_visibles: 1 } });
      }
      return Promise.resolve({ data: {} });
    });
    api.patch.mockResolvedValue({ data: { mensaje: 'ok' } });
  });

  it('stacks unread compras.* banners and OK marks DESCARTADA without localStorage', async () => {
    const user = userEvent.setup();
    renderWithRouter(<AppLayout />, { initialEntries: ['/'] });

    const banner = await screen.findByText(/Factura FA-99 cargada en P-01-2026-00012/);
    expect(banner).toBeInTheDocument();
    expect(screen.queryByText('Markup bajo')).not.toBeInTheDocument();
    expect(localStorage.getItem('alertBanner_compras-11_dismissed')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Cerrar alerta' }));

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/notificaciones/11/ok');
    });
    await waitFor(() => {
      expect(screen.queryByText(/Factura FA-99 cargada en P-01-2026-00012/)).not.toBeInTheDocument();
    });
    expect(localStorage.getItem('alertBanner_compras-11_dismissed')).toBeNull();
  });
});
