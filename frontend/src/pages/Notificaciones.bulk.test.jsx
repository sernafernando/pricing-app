/**
 * Group actions send ONE bulk request, never one request per notification.
 *
 * Prod incident 2026-11-18: ignoring a group of 1411 notifications sent 1411
 * concurrent requests and took the API down.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import api from '../services/api';
import Notificaciones from './Notificaciones';
import NotificationBell from '../components/NotificationBell';

vi.mock('../contexts/SSEContext', () => ({
  SSEProvider: ({ children }) => children,
  useSSE: () => ({ isDegraded: () => false, subscribe: () => () => {} }),
}));

vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: () => {},
}));

const IDS = Array.from({ length: 1411 }, (_, i) => 1000 + i);

const grupoFailover = (leida) => ({
  item_id: null,
  tipo: 'ml_bot.llm_failover',
  markup_real: null,
  codigo_producto: null,
  descripcion_producto: null,
  pm: null,
  count: IDS.length,
  primera_fecha: '2026-07-30T23:09:00Z',
  ultima_fecha: '2026-11-14T23:11:00Z',
  notificacion_reciente: {
    id: IDS[IDS.length - 1],
    tipo: 'ml_bot.llm_failover',
    mensaje: "Bot ML: el proveedor LLM 'openrouter' falló — failover activo a 'groq'.",
    leida,
    severidad: 'WARNING',
    estado: 'PENDIENTE',
    fecha_creacion: '2026-11-14T23:11:00Z',
  },
  notificaciones_ids: IDS,
});

const stats = {
  total: 1411,
  no_leidas: 1411,
  por_tipo: {},
  no_leidas_por_familia: { compras: 0, markup: 0, tecnicas: 1411, otras: 0 },
};

const mockServer = (leida) => {
  api.get.mockImplementation((url) => {
    if (url === '/notificaciones/stats') return Promise.resolve({ data: stats });
    if (url === '/notificaciones/agrupadas') return Promise.resolve({ data: [grupoFailover(leida)] });
    if (url === '/notificaciones/total') return Promise.resolve({ data: { total: 1411, pms: [] } });
    return Promise.resolve({ data: [] });
  });
  api.post.mockResolvedValue({ data: { count: IDS.length } });
};

const expectOneBulk = async (accion) => {
  await waitFor(() => {
    expect(api.post).toHaveBeenCalledWith('/notificaciones/bulk', { ids: IDS, accion });
  });
  const bulkCalls = api.post.mock.calls.filter(([url]) => url === '/notificaciones/bulk');
  expect(bulkCalls).toHaveLength(1);
  expect(api.patch).not.toHaveBeenCalled();
  expect(api.delete).not.toHaveBeenCalled();
};

describe('Notificaciones page — group actions are one request', () => {
  beforeEach(() => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.spyOn(window, 'alert').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const expandir = async (user) => {
    await user.click(await screen.findByText(/el proveedor LLM 'openrouter' falló/));
  };

  it('expanding an unread group marks all of it read in one request', async () => {
    mockServer(false);
    const user = userEvent.setup();
    renderWithRouter(<Notificaciones />);

    await expandir(user);

    await expectOneBulk('leida');
  });

  it.each([
    ['Ignorar (1411)', 'descartada'],
    ['Revisada (1411)', 'revisada'],
    ['Resuelta (1411)', 'resuelta'],
    ['○ Marcar no leídas (1411)', 'no_leida'],
    ['🗑️ Eliminar (1411)', 'eliminar'],
  ])('"%s" sends one bulk request with action %s', async (boton, accion) => {
    mockServer(true);
    const user = userEvent.setup();
    renderWithRouter(<Notificaciones />);

    await expandir(user);
    await user.click(screen.getByRole('button', { name: boton }));

    await expectOneBulk(accion);
  });

  it('a failed group action is shown on the page, not in a browser popup', async () => {
    mockServer(true);
    api.post.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    renderWithRouter(<Notificaciones />);

    await expandir(user);
    await user.click(screen.getByRole('button', { name: 'Resuelta (1411)' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo aplicar la acción al grupo');
    expect(window.alert).not.toHaveBeenCalled();
  });
});

describe('NotificationBell — group actions are one request', () => {
  it.each([
    ['Marcar como leída', 'leida'],
    ['Eliminar', 'eliminar'],
  ])('"%s" sends one bulk request with action %s', async (titulo, accion) => {
    mockServer(false);
    const user = userEvent.setup();
    renderWithRouter(<NotificationBell />);

    await user.click(screen.getByRole('button', { name: 'Notificaciones' }));
    await screen.findByText(/el proveedor LLM 'openrouter' falló/);
    await user.click(screen.getByTitle(titulo));

    await expectOneBulk(accion);
  });
});
