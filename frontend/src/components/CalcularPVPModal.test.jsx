/**
 * Explicit write set (Publicaciones ML): with `itemIds` the modal sends exactly those products as `item_ids`,
 * never `filtros`, offers no "all products" option and shows the count. Without it, Productos' path is unchanged
 * (pinned in masivoFilterParity.test.jsx).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CalcularPVPModal from './CalcularPVPModal';
import api from '../services/api';

vi.mock('../services/api', () => ({
  default: { post: vi.fn().mockResolvedValue({ data: { procesados: 3 } }), get: vi.fn() },
}));

function renderModal(props = {}) {
  return render(<CalcularPVPModal onClose={() => {}} onSuccess={() => {}} showToast={() => {}} {...props} />);
}

describe('CalcularPVPModal with itemIds', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('confirm', () => true);
  });

  it('sends exactly the given products and no filtros', async () => {
    renderModal({ itemIds: [7, 8, 9] });
    await userEvent.setup().click(screen.getByRole('button', { name: /calcular/i }));
    expect(api.post).toHaveBeenCalledTimes(1);
    const [url, body] = api.post.mock.calls[0];
    expect(url).toBe('/productos/calcular-pvp-masivo');
    expect(body.item_ids).toEqual([7, 8, 9]);
    expect(body).not.toHaveProperty('filtros');
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
