/**
 * ODD `ventas-ml-ui-pendiente` T7: the panel's "Resincronizar" action and the
 * "Sincronizado hace X" indicator. The button exists only for who holds
 * `ml_ops.resincronizar` (the page passes `canResync`); a failure is shown
 * and leaves the shown data alone.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SaleDetailPanel from './SaleDetailPanel';
import api from '../../services/api';

const DETAIL = {
  breakdown: { lines: [], neto: 1, incompleto: false, incomplete_reasons: [], item_lines: [] },
  order: { order_id: 77, buyer_nickname: 'x' },
};

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ data: DETAIL });
});

function panel(props = {}) {
  return render(<SaleDetailPanel orderId={77} onClose={vi.fn()} {...props} />);
}

describe('permission gate', () => {
  it('hides the button without the permission', async () => {
    panel({ canResync: false });
    await screen.findByText('Desglose de costos');
    expect(screen.queryByRole('button', { name: /resincronizar/i })).not.toBeInTheDocument();
  });

  it('shows it with the permission', async () => {
    panel({ canResync: true });
    expect(await screen.findByRole('button', { name: /resincronizar/i })).toBeEnabled();
  });
});

describe('resync', () => {
  it('posts to the order, reloads the detail and tells the page', async () => {
    api.post.mockResolvedValue({ data: { order_id: 77, order_changed: true } });
    const onResynced = vi.fn();
    const user = userEvent.setup();
    panel({ canResync: true, onResynced });
    await user.click(await screen.findByRole('button', { name: /resincronizar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ml-ventas-ops/orders/77/resync'));
    await waitFor(() => expect(onResynced).toHaveBeenCalledTimes(1));
    expect(api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/orders/77').length).toBe(2);
    expect(await screen.findByText(/resincronizada/i)).toBeInTheDocument();
  });

  it('is disabled while it runs, so a double click cannot fire twice', async () => {
    let resolve;
    api.post.mockReturnValue(new Promise((r) => { resolve = r; }));
    const user = userEvent.setup();
    panel({ canResync: true });
    await user.click(await screen.findByRole('button', { name: /resincronizar/i }));
    expect(screen.getByRole('button', { name: /resincronizando/i })).toBeDisabled();
    resolve({ data: { order_id: 77, order_changed: false } });
    await waitFor(() => expect(screen.getByRole('button', { name: /^resincronizar$/i })).toBeEnabled());
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('shows the backend message on failure and does not reload or notify', async () => {
    api.post.mockRejectedValue({
      response: { status: 502, data: { detail: 'No se pudo traer la venta desde Mercado Libre. Los datos guardados no cambiaron.' } },
    });
    const onResynced = vi.fn();
    const user = userEvent.setup();
    panel({ canResync: true, onResynced });
    await user.click(await screen.findByRole('button', { name: /resincronizar/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Los datos guardados no cambiaron');
    expect(onResynced).not.toHaveBeenCalled();
    expect(api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/orders/77').length).toBe(1);
    expect(screen.getByRole('button', { name: /^resincronizar$/i })).toBeEnabled();
  });

  it('uses a generic message when the failure carries none', async () => {
    api.post.mockRejectedValue(new Error('network'));
    const user = userEvent.setup();
    panel({ canResync: true });
    await user.click(await screen.findByRole('button', { name: /resincronizar/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo resincronizar la venta.');
  });
});

describe('Sincronizado hace X', () => {
  it('shows how long ago the list was last synced', async () => {
    const lastSyncedAt = new Date(Date.now() - 3 * 60_000).toISOString();
    panel({ canResync: true, lastSyncedAt });
    expect(await screen.findByText('Sincronizado hace 3 min')).toBeInTheDocument();
  });

  it('claims nothing when there is no sync timestamp', async () => {
    panel({ canResync: true, lastSyncedAt: null });
    await screen.findByText('Desglose de costos');
    expect(screen.queryByText(/Sincronizado/)).not.toBeInTheDocument();
  });
});
