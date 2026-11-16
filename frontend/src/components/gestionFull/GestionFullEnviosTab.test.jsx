import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import GestionFullEnviosTab from './GestionFullEnviosTab';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
  },
}));

import api from '../../services/api';

describe('GestionFullEnviosTab', () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it('loads envíos and opens detail', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/gestion-full/envios') {
        return Promise.resolve({
          data: [
            {
              inbound_id: '79909756',
              human_id: '20261027_79909756',
              week_monday: '2026-10-27',
              last_reception_at: null,
              reception_closed: false,
            },
          ],
        });
      }
      if (url === '/gestion-full/envios/79909756') {
        return Promise.resolve({
          data: {
            inbound_id: '79909756',
            human_id: '20261027_79909756',
            lines: [],
          },
        });
      }
      return Promise.reject(new Error(`unexpected ${url}`));
    });

    render(<GestionFullEnviosTab />);

    expect(screen.getByLabelText('Incluir recepción cerrada')).toBeInTheDocument();

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/gestion-full/envios',
        expect.objectContaining({
          params: { include_closed: false },
        }),
      );
    });
    await waitFor(() => {
      expect(screen.getByText('79909756')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Detalle' }));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/gestion-full/envios/79909756');
    });
    expect(screen.queryByRole('button', { name: 'Excel ops' })).not.toBeInTheDocument();
  });

  it('shows Excel ops for gestor and downloads on click', async () => {
    const blob = new Blob(['xlsx'], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    api.get.mockImplementation((url, opts) => {
      if (url === '/gestion-full/envios') {
        return Promise.resolve({
          data: [
            {
              inbound_id: '79909756',
              human_id: '20261027_79909756',
              week_monday: '2026-10-27',
              last_reception_at: null,
              reception_closed: false,
            },
          ],
        });
      }
      if (url === '/gestion-full/envios/79909756') {
        return Promise.resolve({
          data: {
            inbound_id: '79909756',
            human_id: '20261027_79909756',
            lines: [{ inventory_id: 'INV1', user_product_id: 'MLAU1', declared: 2, received: 0, diff: -2 }],
          },
        });
      }
      if (url === '/gestion-full/envios/79909756/export/ops') {
        expect(opts).toEqual(expect.objectContaining({ responseType: 'blob' }));
        return Promise.resolve({ data: blob });
      }
      return Promise.reject(new Error(`unexpected ${url}`));
    });

    const createObjectURL = vi.fn(() => 'blob:ops');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });

    render(<GestionFullEnviosTab puedeGestor />);
    await waitFor(() => {
      expect(screen.getByText('79909756')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Detalle' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Excel ops' })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Excel ops' }));
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/gestion-full/envios/79909756/export/ops',
        expect.objectContaining({ responseType: 'blob' }),
      );
    });
    await waitFor(() => {
      expect(screen.getByText(/Descarga ops/i)).toBeInTheDocument();
    });
  });

  it('shows empty state when there are no local envíos', async () => {
    api.get.mockResolvedValue({ data: [] });
    render(<GestionFullEnviosTab />);
    await waitFor(() => {
      expect(screen.getByText(/Sin envíos locales/i)).toBeInTheDocument();
    });
  });
});
