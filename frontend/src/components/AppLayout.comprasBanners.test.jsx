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

  it('caps 7 unread compras banners at 3 and shows +4 más', async () => {
    const seven = Array.from({ length: 7 }, (_, index) => ({
      id: 200 + index,
      tipo: 'compras.factura_cargada',
      estado: 'PENDIENTE',
      mensaje: `Factura FA-${index + 1} cargada en P-01-2026-00012 (Acme).`,
      item_id: 42,
      leida: false,
    }));
    api.get.mockImplementation((url) => {
      if (url === '/notificaciones') {
        return Promise.resolve({ data: seven });
      }
      if (url === '/alertas/activas') {
        return Promise.resolve({ data: [] });
      }
      if (url === '/alertas/configuracion') {
        return Promise.resolve({ data: { max_alertas_visibles: 3 } });
      }
      return Promise.resolve({ data: {} });
    });

    renderWithRouter(<AppLayout />, { initialEntries: ['/'] });

    expect(await screen.findByText('+4 más')).toBeInTheDocument();
    expect(screen.getAllByText(/Factura FA-\d+ cargada/)).toHaveLength(3);
    expect(screen.getByText(/Factura FA-1 cargada/)).toBeInTheDocument();
    expect(screen.getByText(/Factura FA-3 cargada/)).toBeInTheDocument();
    expect(screen.queryByText(/Factura FA-4 cargada/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Factura FA-7 cargada/)).not.toBeInTheDocument();
  });

  it('keeps unread compras banners until OK and does not timed-rotate them', async () => {
    const seven = Array.from({ length: 7 }, (_, index) => ({
      id: 300 + index,
      tipo: 'compras.factura_cargada',
      estado: 'PENDIENTE',
      mensaje: `Factura FA-${index + 1} persistente en P-01-2026-00012 (Acme).`,
      item_id: 42,
      leida: false,
    }));
    api.get.mockImplementation((url) => {
      if (url === '/notificaciones') {
        return Promise.resolve({ data: seven });
      }
      if (url === '/alertas/activas') {
        return Promise.resolve({ data: [] });
      }
      if (url === '/alertas/configuracion') {
        return Promise.resolve({ data: { max_alertas_visibles: 3 } });
      }
      return Promise.resolve({ data: {} });
    });

    const user = userEvent.setup();
    renderWithRouter(<AppLayout />, { initialEntries: ['/'] });

    expect(await screen.findByText('+4 más')).toBeInTheDocument();
    expect(screen.getByText(/Factura FA-1 persistente/)).toBeInTheDocument();
    expect(screen.getAllByText(/Factura FA-\d+ persistente/)).toHaveLength(3);

    await user.click(screen.getAllByRole('button', { name: 'Cerrar alerta' })[0]);
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/notificaciones/300/ok');
    });
    await waitFor(() => {
      expect(screen.queryByText(/Factura FA-1 persistente/)).not.toBeInTheDocument();
    });
    expect(screen.getByText(/Factura FA-2 persistente/)).toBeInTheDocument();
    expect(screen.getByText('+3 más')).toBeInTheDocument();
  });

  it('does not dismiss compras.faltantes; Ver and Posponer stay, no /ok', async () => {
    const user = userEvent.setup();
    const faltantesNotif = {
      id: 77,
      tipo: 'compras.faltantes',
      estado: 'PENDIENTE',
      mensaje: 'Faltantes en P-01-2026-00012 (Acme). Resolver en Pedidos.',
      item_id: 42,
      leida: false,
    };
    api.get.mockImplementation((url) => {
      if (url === '/notificaciones') {
        return Promise.resolve({ data: [faltantesNotif] });
      }
      if (url === '/alertas/activas') {
        return Promise.resolve({ data: [] });
      }
      if (url === '/alertas/configuracion') {
        return Promise.resolve({ data: { max_alertas_visibles: 1 } });
      }
      return Promise.resolve({ data: {} });
    });

    renderWithRouter(<AppLayout />, { initialEntries: ['/'] });

    expect(await screen.findByText(/Faltantes en P-01-2026-00012/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ver' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Posponer' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cerrar alerta' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Posponer' }));
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/notificaciones/77/snooze');
    });
    expect(api.patch).not.toHaveBeenCalledWith('/notificaciones/77/ok');
    await waitFor(() => {
      expect(screen.queryByText(/Faltantes en P-01-2026-00012/)).not.toBeInTheDocument();
    });
  });
});
