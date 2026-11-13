/**
 * MejoresOfertasPmsBadge: whoever reviews the PMs (alertas.ver_mejores_ofertas_pms) sees
 * every PM's better offers grouped, and each PM opens that PM's filtered page.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

const sse = vi.hoisted(() => ({ handlers: {} }));
const permisos = vi.hoisted(() => ({ codes: ['alertas.ver_mejores_ofertas_pms'] }));

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));
vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: (channel, handler, { enabled }) => {
    if (enabled) sse.handlers[channel] = handler;
  },
}));
vi.mock('../contexts/SSEContext', () => ({ useSSE: () => ({ isDegraded: () => false }) }));
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (codigo) => permisos.codes.includes(codigo) }),
}));

import api from '../services/api';
import MejoresOfertasPmsBadge from './MejoresOfertasPmsBadge';

const URL = '/ml-publications/view/mejores-ofertas/por-pm';
const BODY = {
  pms: [
    { pm_id: 17, nombre: 'Carolina Lépore', count: 12 },
    { pm_id: 3, nombre: 'Ramiro Echeverría', count: 4 },
    { pm_id: 9, nombre: 'Juan Pereyra', count: 0 },
  ],
  total: 16,
};

const renderBadge = () =>
  render(
    <MemoryRouter>
      <MejoresOfertasPmsBadge />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  sse.handlers = {};
  permisos.codes = ['alertas.ver_mejores_ofertas_pms'];
});

describe('MejoresOfertasPmsBadge', () => {
  it('shows the total and, opened, each PM with their count linking to their filtered page', async () => {
    api.get.mockResolvedValue({ data: BODY });
    renderBadge();
    const button = await screen.findByRole('button', { name: 'Promos mejores por PM: 16 en total' });
    expect(button).toHaveTextContent('16');
    expect(api.get).toHaveBeenCalledWith(URL);

    await userEvent.click(button);
    const links = screen.getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual(['Carolina Lépore12', 'Ramiro Echeverría4', 'Juan Pereyra0']);
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=17',
      '/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=3',
      '/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=9',
    ]);
  });

  it('closes on Escape', async () => {
    api.get.mockResolvedValue({ data: BODY });
    renderBadge();
    await userEvent.click(await screen.findByRole('button', { name: /16 en total/ }));
    expect(screen.getByRole('dialog', { name: 'Promos mejores por PM' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('never asks without the permission, even with the screen permissions', () => {
    permisos.codes = ['productos.ver', 'ml_ops.ver'];
    const { container } = renderBadge();
    expect(container).toBeEmptyDOMElement();
    expect(api.get).not.toHaveBeenCalled();
    expect(sse.handlers).toEqual({});
  });

  it('renders nothing while no PM has anything to review', async () => {
    api.get.mockResolvedValue({ data: { pms: [{ pm_id: 9, nombre: 'Juan Pereyra', count: 0 }], total: 0 } });
    const { container } = renderBadge();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("re-reads on the PM badge's SSE channel", async () => {
    api.get.mockResolvedValueOnce({ data: BODY });
    renderBadge();
    await screen.findByRole('button', { name: /16 en total/ });
    vi.useFakeTimers();
    try {
      api.get.mockResolvedValue({ data: { ...BODY, total: 20 } });
      sse.handlers['ml-publications:mejores-ofertas']();
      await vi.advanceTimersByTimeAsync(10000);
      expect(api.get).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
    expect(await screen.findByRole('button', { name: /20 en total/ })).toBeInTheDocument();
  });
});
