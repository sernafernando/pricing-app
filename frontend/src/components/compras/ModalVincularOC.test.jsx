import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import api from '../../services/api';
import ModalVincularOC from './ModalVincularOC';

// The global PermisosContext mock in src/test/setup.js grants every permission.

afterEach(() => {
  vi.clearAllMocks();
});

describe('ModalVincularOC — servicio', () => {
  it('shows empty candidates for tipo=servicio without fetching', async () => {
    api.get.mockResolvedValue({ data: [{ oc_poh_id: 99, oc_comp_id: 1, oc_bra_id: 1 }] });
    render(
      <ModalVincularOC
        pedido={{ id: 7, numero: 'PC-SERV', tipo: 'servicio' }}
        onClose={() => {}}
        onVinculada={() => {}}
      />
    );

    expect(
      await screen.findByText('Los pedidos de servicio no admiten órdenes de compra.')
    ).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
