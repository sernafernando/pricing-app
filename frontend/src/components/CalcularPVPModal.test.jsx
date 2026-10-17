/**
 * Explicit write set (Publicaciones ML): with `itemIds` the modal sends exactly those products as `item_ids`,
 * never `filtros`, offers no "all products" option and shows the count. Without it, Productos' path is unchanged
 * (pinned in masivoFilterParity.test.jsx).
 *
 * The run is confirmed in an in-app Tesla dialog, never the browser's `confirm()`.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CalcularPVPModal from './CalcularPVPModal';
import api from '../services/api';

vi.mock('../services/api', () => ({
  default: { post: vi.fn().mockResolvedValue({ data: { procesados: 3 } }), get: vi.fn() },
}));

function renderModal(props = {}) {
  return render(<CalcularPVPModal onClose={() => {}} onSuccess={() => {}} showToast={() => {}} {...props} />);
}

async function openConfirmation(user) {
  await user.click(screen.getByRole('button', { name: /calcular/i }));
  const message = await screen.findByText('¿Confirmar el cálculo para 3 productos?');
  return within(message.closest('.modal-tesla'));
}

describe('CalcularPVPModal with itemIds', () => {
  let nativeConfirm;

  beforeEach(() => {
    vi.clearAllMocks();
    nativeConfirm = vi.fn(() => true);
    vi.stubGlobal('confirm', nativeConfirm);
  });

  afterEach(() => vi.unstubAllGlobals());

  it('asks in-app, and only once confirmed sends exactly the given products and no filtros', async () => {
    renderModal({ itemIds: [7, 8, 9] });
    const user = userEvent.setup();
    const dialog = await openConfirmation(user);
    expect(api.post).not.toHaveBeenCalled();

    await user.click(dialog.getByRole('button', { name: 'Confirmar' }));
    expect(api.post).toHaveBeenCalledTimes(1);
    const [url, body] = api.post.mock.calls[0];
    expect(url).toBe('/productos/calcular-pvp-masivo');
    expect(body.item_ids).toEqual([7, 8, 9]);
    expect(body).not.toHaveProperty('filtros');
    expect(nativeConfirm).not.toHaveBeenCalled();
  });

  it('cancelling the confirmation sends nothing and keeps the modal open', async () => {
    renderModal({ itemIds: [7, 8, 9] });
    const user = userEvent.setup();
    const dialog = await openConfirmation(user);

    await user.click(dialog.getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByText('¿Confirmar el cálculo para 3 productos?')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /calcular/i })).toBeEnabled();
    expect(api.post).not.toHaveBeenCalled();
    expect(nativeConfirm).not.toHaveBeenCalled();
  });

  it('shows the count and the caller note, with no "all products" option', () => {
    renderModal({ itemIds: [7, 8, 9], itemIdsNota: '2 publicaciones sin producto quedan afuera' });
    expect(screen.getByText(/3 productos/i)).toBeInTheDocument();
    expect(screen.getByText('2 publicaciones sin producto quedan afuera')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('an empty set cannot run', () => {
    renderModal({ itemIds: [] });
    expect(screen.getByRole('button', { name: /calcular/i })).toBeDisabled();
  });
});
