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
  });

  it('shows empty state when there are no local envíos', async () => {
    api.get.mockResolvedValue({ data: [] });
    render(<GestionFullEnviosTab />);
    await waitFor(() => {
      expect(screen.getByText(/Sin envíos locales/i)).toBeInTheDocument();
    });
  });
});
