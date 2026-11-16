/**
 * Bell: family tabs with unread counts, server-side family filter, and
 * non-markup notifications rendering their own message (owner 2026-11-16).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import api from '../services/api';
import NotificationBell from './NotificationBell';

const sseStub = { isDegraded: () => false, subscribe: () => () => {} };
vi.mock('../contexts/SSEContext', () => ({
  SSEProvider: ({ children }) => children,
  useSSE: () => sseStub,
}));

vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: () => {},
}));

const notif = (overrides) => ({
  id: 1,
  tipo: 'markup_bajo',
  mensaje: 'Markup bajo',
  leida: false,
  severidad: 'INFO',
  estado: 'PENDIENTE',
  ...overrides,
});

const grupoFactura = {
  item_id: 321,
  tipo: 'compras.factura_cargada',
  markup_real: null,
  codigo_producto: null,
  descripcion_producto: null,
  pm: null,
  count: 1,
  primera_fecha: '2026-11-13T09:00:00Z',
  ultima_fecha: '2026-11-13T09:00:00Z',
  notificacion_reciente: notif({
    id: 371433,
    tipo: 'compras.factura_cargada',
    mensaje: 'Factura 00002-00006138 cargada en P-321 (Proveedor SA).',
  }),
  notificaciones_ids: [371433],
};

const grupoMarkup = {
  item_id: 9000,
  tipo: 'markup_bajo',
  markup_real: -4.5,
  codigo_producto: 'COD-9000',
  descripcion_producto: 'Producto 9000',
  pm: 'Gabriel Perez',
  count: 2,
  primera_fecha: '2026-11-14T09:00:00Z',
  ultima_fecha: '2026-11-14T10:00:00Z',
  notificacion_reciente: notif({ id: 5, mensaje: 'Markup bajo en venta' }),
  notificaciones_ids: [4, 5],
};

const stats = {
  total: 1500,
  no_leidas: 1408,
  por_tipo: {},
  no_leidas_por_familia: { compras: 6, markup: 846, tecnicas: 555, otras: 1 },
};

describe('NotificationBell — family tabs', () => {
  beforeEach(() => {
    api.get.mockImplementation((url, config) => {
      if (url === '/notificaciones/stats') return Promise.resolve({ data: stats });
      if (url === '/notificaciones/agrupadas') {
        const familia = config?.params?.familia;
        if (familia === 'compras') return Promise.resolve({ data: [grupoFactura] });
        return Promise.resolve({ data: [grupoMarkup, grupoFactura] });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it('shows one tab per family with its unread count', async () => {
    const user = userEvent.setup();
    renderWithRouter(<NotificationBell />);

    await user.click(screen.getByRole('button', { name: 'Notificaciones' }));

    const tabs = await screen.findByRole('tablist', { name: 'Familias de notificaciones' });
    expect(within(tabs).getByRole('tab', { name: /Todas\s*1408/ })).toHaveAttribute('aria-selected', 'true');
    expect(within(tabs).getByRole('tab', { name: /Compras\s*6/ })).toBeInTheDocument();
    expect(within(tabs).getByRole('tab', { name: /Markup\s*846/ })).toBeInTheDocument();
    expect(within(tabs).getByRole('tab', { name: /Técnicas\s*555/ })).toBeInTheDocument();
    expect(within(tabs).getByRole('tab', { name: /Otras\s*1/ })).toBeInTheDocument();
  });

  it('the Compras tab asks the server for that family', async () => {
    const user = userEvent.setup();
    renderWithRouter(<NotificationBell />);

    await user.click(screen.getByRole('button', { name: 'Notificaciones' }));
    await user.click(await screen.findByRole('tab', { name: /Compras/ }));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/notificaciones/agrupadas', {
        params: { solo_no_leidas: false, familia: 'compras' },
      });
    });
    expect(await screen.findByText(/Factura 00002-00006138 cargada en P-321/)).toBeInTheDocument();
    expect(screen.queryByText('COD-9000 - Producto 9000')).not.toBeInTheDocument();
  });

  it('a compras group shows its own title and never a product line', async () => {
    const user = userEvent.setup();
    renderWithRouter(<NotificationBell />);

    await user.click(screen.getByRole('button', { name: 'Notificaciones' }));

    const factura = await screen.findByText(/Factura 00002-00006138 cargada en P-321/);
    const item = factura.closest('[data-testid="notif-item"]');
    expect(within(item).getByText('Factura cargada')).toBeInTheDocument();
    expect(within(item).getByText('🧾')).toBeInTheDocument();
    expect(within(item).queryByText(/ - /)).not.toBeInTheDocument();
  });
});
