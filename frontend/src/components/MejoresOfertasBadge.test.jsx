/**
 * MejoresOfertasBadge: a PM sees how many of THEIR active publications have better
 * offers and opens their filtered Publicaciones ML page; nobody else sees it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const sse = vi.hoisted(() => ({ handlers: {} }));
const permisos = vi.hoisted(() => ({ codes: ['productos.ver'] }));

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
import MejoresOfertasBadge from './MejoresOfertasBadge';

const URL = '/ml-publications/view/mejores-ofertas/count';

const renderBadge = () =>
  render(
    <MemoryRouter>
      <MejoresOfertasBadge />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  sse.handlers = {};
  permisos.codes = ['productos.ver'];
});

afterEach(() => {
  vi.restoreAllMocks(); // a failed assertion never leaves Date.now or console spied for the next test
});

describe('MejoresOfertasBadge', () => {
  it("shows the owner's sentence with the count and links to the PM's filtered page", async () => {
    api.get.mockResolvedValue({ data: { pm_id: 17, count: 5 } });
    renderBadge();
    const link = await screen.findByRole('link', { name: 'tenés 5 promos mejores para revisar' });
    expect(link).toHaveAttribute('href', '/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=17');
    expect(link).toHaveTextContent('tenés 5 promos mejores para revisar');
    expect(api.get).toHaveBeenCalledWith(URL);
  });

  it('uses the singular for one, as the top bar badges pluralize their counts', async () => {
    api.get.mockResolvedValue({ data: { pm_id: 17, count: 1 } });
    renderBadge();
    expect(await screen.findByRole('link', { name: 'tenés 1 promo mejor para revisar' })).toBeInTheDocument();
  });

  it('renders nothing for a user who is not a PM', async () => {
    api.get.mockResolvedValue({ data: { pm_id: null, count: 0 } });
    const { container } = renderBadge();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('logs a failed read and renders nothing', async () => {
    const error = new Error('Network Error');
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    api.get.mockRejectedValue(error);
    const { container } = renderBadge();
    await waitFor(() => expect(log).toHaveBeenCalledWith('Mejores ofertas: the PM count request failed', error));
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing while the PM has no better offers', async () => {
    api.get.mockResolvedValue({ data: { pm_id: 17, count: 0 } });
    const { container } = renderBadge();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('never asks without a Publicaciones ML permission', async () => {
    permisos.codes = [];
    const { container } = renderBadge();
    expect(container).toBeEmptyDOMElement();
    expect(api.get).not.toHaveBeenCalled();
    expect(sse.handlers).toEqual({});
  });

  it('ml_ops.ver alone also shows it', async () => {
    permisos.codes = ['ml_ops.ver'];
    api.get.mockResolvedValue({ data: { pm_id: 3, count: 2 } });
    renderBadge();
    expect(await screen.findByRole('link', { name: 'tenés 2 promos mejores para revisar' })).toBeInTheDocument();
  });

  it('re-reads the count on its SSE channel', async () => {
    api.get.mockResolvedValueOnce({ data: { pm_id: 17, count: 5 } });
    renderBadge();
    await screen.findByRole('link', { name: 'tenés 5 promos mejores para revisar' });
    api.get.mockResolvedValueOnce({ data: { pm_id: 17, count: 0 } });
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 11000); // past the 10 s debounce, as FreeShippingBadge
    sse.handlers['ml-publications:mejores-ofertas']();
    await waitFor(() => expect(screen.queryByRole('link')).not.toBeInTheDocument());
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it('a signal inside the 10 s window reads once when the window ends, never dropped', async () => {
    api.get.mockResolvedValueOnce({ data: { pm_id: 17, count: 5 } });
    renderBadge();
    await screen.findByRole('link', { name: 'tenés 5 promos mejores para revisar' });
    vi.useFakeTimers();
    try {
      api.get.mockResolvedValue({ data: { pm_id: 17, count: 7 } });
      sse.handlers['ml-publications:mejores-ofertas']();
      sse.handlers['ml-publications:mejores-ofertas'](); // a burst of commits: still one read
      expect(api.get).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(10000);
      expect(api.get).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
    expect(await screen.findByRole('link', { name: 'tenés 7 promos mejores para revisar' })).toBeInTheDocument();
  });
});
