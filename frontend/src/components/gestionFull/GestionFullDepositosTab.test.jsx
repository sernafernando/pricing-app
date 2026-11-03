import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import GestionFullDepositosTab from './GestionFullDepositosTab';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock('../../hooks/useDebounce', () => ({
  useDebounce: (value) => value,
}));

import api from '../../services/api';

describe('GestionFullDepositosTab', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.patch.mockReset();
  });

  it('defaults to pendientes and loads the pendientes endpoint', async () => {
    api.get.mockResolvedValue({
      data: {
        items: [
          {
            producto_item_id: 7,
            ean: 'EAN-7',
            descripcion: 'Caja pendiente',
            en_paquete: true,
            pm_ready: false,
          },
        ],
      },
    });

    render(<GestionFullDepositosTab />);

    expect(screen.getByRole('group', { name: 'Vista depósito' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Pendientes' })).toBeInTheDocument();
    expect(screen.getByLabelText('Importar unidades por caja')).toBeInTheDocument();

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/gestion-full/unidades-caja/pendientes',
        expect.objectContaining({
          params: expect.objectContaining({ q: undefined }),
        }),
      );
    });
    await waitFor(() => {
      expect(screen.getByText('EAN-7')).toBeInTheDocument();
    });
  });
});
