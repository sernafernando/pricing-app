import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import GestionFullGestorTab from './GestionFullGestorTab';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import api from '../../services/api';

describe('GestionFullGestorTab', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
  });

  it('loads package lines and assigns inbound to selection', async () => {
    api.get.mockResolvedValue({
      data: {
        id: 1,
        week_monday: '2026-10-26',
        status: 'exported',
        lines: [
          {
            id: 10,
            producto_item_id: 1,
            user_product_id: 'MLAU1',
            inventory_id: 'INV1',
            qty_pm: 5,
            qty_export: 5,
            inbound_id: null,
          },
        ],
      },
    });
    api.post.mockResolvedValue({ data: {} });

    render(<GestionFullGestorTab />);
    await waitFor(() => expect(screen.getByText('INV1')).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText('Seleccionar línea 10'));
    fireEvent.change(screen.getByLabelText('inbound_id'), { target: { value: '81061502' } });
    fireEvent.click(screen.getByRole('button', { name: /Asignar a selección/ }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/gestion-full/package/assign-inbound', {
        inbound_id: '81061502',
        line_ids: [10],
      });
    });
  });
});
