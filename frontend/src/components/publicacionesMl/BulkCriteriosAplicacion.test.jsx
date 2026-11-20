import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BulkCriteriosAplicacion from './BulkCriteriosAplicacion';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: (code) => code === 'promos.escribir' || code === 'promos.auto_aplicacion',
  }),
}));

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    setHayMejoresCriteriosBulk: vi.fn(),
  },
  publicacionesMlAPI: {
    hayMejoresCriteriosItemIds: vi.fn(),
    hayMejoresCriteriosItemIdsChecked: vi.fn(),
  },
}));

import { promocionesAPI, publicacionesMlAPI } from '../../services/api';

describe('BulkCriteriosAplicacion', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    publicacionesMlAPI.hayMejoresCriteriosItemIdsChecked.mockResolvedValue({
      data: { item_ids: ['MLA1', 'MLA2'], no_aplican: 0 },
    });
    promocionesAPI.setHayMejoresCriteriosBulk.mockResolvedValue({
      data: { count: 2, descartadas: ['MLA1'], omitidas_auto_fail: [], auto_on_previas: 1 },
    });
  });

  it('opens the modal, can discard suggestions, and omits Auto when unchecked', async () => {
    const user = userEvent.setup();
    const menuSlot = document.createElement('div');
    document.body.appendChild(menuSlot);
    render(
      <BulkCriteriosAplicacion
        filters={{}}
        canSeeMargin
        checked={{ itemIds: ['MLA1'], productIds: [] }}
        menuSlot={menuSlot}
      />,
    );
    await user.click(screen.getByRole('menuitem', { name: /criterios de hay mejores/i }));
    await waitFor(() => expect(screen.getByText(/Se van a aplicar estos criterios/i)).toBeInTheDocument());
    const discard = screen.getByRole('checkbox', { name: /descartar sugerencias/i });
    expect(discard).not.toBeChecked();
    await user.click(discard);
    expect(discard).toBeChecked();
    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await waitFor(() => expect(promocionesAPI.setHayMejoresCriteriosBulk).toHaveBeenCalled());
    const body = promocionesAPI.setHayMejoresCriteriosBulk.mock.calls[0][0];
    expect(body).not.toHaveProperty('auto_aplicacion');
    expect(body.descartar_sugerencias).toBe(true);
    expect(body.item_ids).toEqual(['MLA1', 'MLA2']);
    document.body.removeChild(menuSlot);
  });
});
