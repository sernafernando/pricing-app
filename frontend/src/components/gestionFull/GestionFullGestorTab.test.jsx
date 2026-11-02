import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import GestionFullGestorTab from './GestionFullGestorTab';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

import api from '../../services/api';

describe('GestionFullGestorTab', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.patch.mockReset();
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

  it('sums ready lines via server endpoint', async () => {
    api.get.mockResolvedValue({
      data: { id: 1, week_monday: '2026-10-26', status: 'open', lines: [] },
    });
    api.post.mockResolvedValue({ data: { package_id: 1, status: 'open', touched: 3 } });

    render(<GestionFullGestorTab />);
    await waitFor(() => expect(screen.getByText(/Paquete #1/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /Sumar líneas Listo/ }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/gestion-full/package/lines/from-ready');
    });
    await waitFor(() => {
      expect(screen.getByText(/Agregadas\/actualizadas 3/)).toBeInTheDocument();
    });
  });

  it('saves qty export on blur', async () => {
    api.get.mockResolvedValue({
      data: {
        id: 1,
        week_monday: '2026-10-26',
        status: 'open',
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
    api.patch.mockResolvedValue({ data: { id: 10, qty_export: 2 } });

    render(<GestionFullGestorTab />);
    const input = await screen.findByLabelText('Qty export línea 10');
    fireEvent.change(input, { target: { value: '2' } });
    fireEvent.blur(input);

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/gestion-full/package/lines/10/qty-export', {
        qty_export: 2,
      });
    });
  });
});
