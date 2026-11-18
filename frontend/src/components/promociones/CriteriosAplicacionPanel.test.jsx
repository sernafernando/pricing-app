import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CriteriosAplicacionPanel from './CriteriosAplicacionPanel';
import { statusQuoGanaCatalogo } from './statusQuoGanaCatalogo';

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    getHayMejoresCriterios: vi.fn(),
    putHayMejoresCriterios: vi.fn(),
    getCompetenciaCatalogo: vi.fn(),
  },
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: (p) => p === 'promos.escribir' || p === 'promos.auto_aplicacion',
  }),
}));

import { promocionesAPI } from '../../services/api';

describe('statusQuoGanaCatalogo', () => {
  it('is true when our_price beats every checked same-bucket rival', () => {
    expect(
      statusQuoGanaCatalogo(
        {
          fetch_status: 'ok',
          our_price: 900,
          same_bucket: [
            { item_id: 'MLA_OURS', price: 900 },
            { item_id: 'MLA_RIVAL', price: 1000 },
          ],
        },
        { mla: 'MLA_OURS' },
      ),
    ).toBe(true);
  });

  it('is false when a checked rival is cheaper or equal', () => {
    expect(
      statusQuoGanaCatalogo(
        {
          fetch_status: 'ok',
          our_price: 1000,
          same_bucket: [{ item_id: 'MLA_RIVAL', price_ars: 950 }],
        },
        { mla: 'MLA_OURS' },
      ),
    ).toBe(false);
  });

  it('ignores excluded item_ids', () => {
    expect(
      statusQuoGanaCatalogo(
        {
          fetch_status: 'ok',
          our_price: 1000,
          same_bucket: [
            { item_id: 'MLA_CHEAP', price: 900 },
            { item_id: 'MLA_DEAR', price: 1100 },
          ],
        },
        { mla: 'MLA_OURS', sellersExcluidos: ['MLA_CHEAP'] },
      ),
    ).toBe(true);
  });

  it('ignores excluded seller_ids (ranking checkboxes)', () => {
    expect(
      statusQuoGanaCatalogo(
        {
          fetch_status: 'ok',
          our_price: 1000,
          same_bucket: [
            { item_id: 'MLA_CHEAP', seller_id: 'S-CHEAP', price: 900 },
            { item_id: 'MLA_DEAR', seller_id: 'S-DEAR', price: 1100 },
          ],
        },
        { mla: 'MLA_OURS', sellersExcluidos: ['S-CHEAP'] },
      ),
    ).toBe(true);
  });

  it('is false when catalog snapshot is stale', () => {
    const stale = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
    expect(
      statusQuoGanaCatalogo(
        {
          fetch_status: 'ok',
          fecha_consulta: stale,
          our_price: 900,
          same_bucket: [
            { item_id: 'MLA_OURS', price: 900 },
            { item_id: 'MLA_RIVAL', price: 1000 },
          ],
        },
        { mla: 'MLA_OURS' },
      ),
    ).toBe(false);
  });
});

describe('CriteriosAplicacionPanel C2 ya ganando banner', () => {
  beforeEach(() => {
    promocionesAPI.getHayMejoresCriterios.mockReset();
    promocionesAPI.putHayMejoresCriterios.mockReset();
    promocionesAPI.getCompetenciaCatalogo.mockReset();
    promocionesAPI.getHayMejoresCriterios.mockResolvedValue({
      data: {
        c1_activo: false,
        c2_activo: false,
        c2_solo_markup_positivo: true,
        auto_aplicacion: false,
        sellers_excluidos: [],
      },
    });
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: {
        fetch_status: 'ok',
        our_price: 900,
        same_bucket: [{ item_id: 'MLA_RIVAL', price: 1000 }],
      },
    });
  });

  it('shows the ya-ganando banner when C2 is on and status quo wins catalog', async () => {
    const user = userEvent.setup();
    render(<CriteriosAplicacionPanel mla="MLA_OURS" />);
    await screen.findByText('C2 — Ganar catálogo');
    await user.click(screen.getByRole('checkbox', { name: /C2 — Ganar catálogo/i }));
    await waitFor(() => {
      expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalledWith('MLA_OURS');
    });
    expect(
      await screen.findByText(/Ya estás ganando el catálogo/, { exact: false }),
    ).toBeInTheDocument();
  });

  it('hides the banner when status quo is not winning', async () => {
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: {
        fetch_status: 'ok',
        our_price: 1000,
        same_bucket: [{ item_id: 'MLA_RIVAL', price: 950 }],
      },
    });
    const user = userEvent.setup();
    render(<CriteriosAplicacionPanel mla="MLA_OURS" />);
    await screen.findByText('C2 — Ganar catálogo');
    await user.click(screen.getByRole('checkbox', { name: /C2 — Ganar catálogo/i }));
    await waitFor(() => {
      expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalled();
    });
    expect(screen.queryByText(/Ya estás ganando el catálogo/, { exact: false })).not.toBeInTheDocument();
  });
});
