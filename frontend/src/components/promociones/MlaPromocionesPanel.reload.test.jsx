// The panel re-reads the mirror after any write attempt. A write that was
// rejected carries no result, so PromoApplyControl reports it through
// `onReloadNeeded` instead of calling `onApplied(null)`; both must reach the
// same re-read.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import { promocionesAPI } from '../../services/api';
import { usePromoFilterStore } from '../../store/promoFilterStore';

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    getPromocionesItem: vi.fn(),
    refreshItemPromociones: vi.fn(),
    confirmarSinPromosML: vi.fn(),
  },
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

// The real control is covered by its own tests; here it only exposes the two
// callbacks the panel hands it.
vi.mock('./PromoApplyControl', () => ({
  default: ({ onApplied, onReloadNeeded }) => (
    <div>
      <button type="button" onClick={() => onApplied({ status: 'submitted' })}>
        stub-applied
      </button>
      <button type="button" onClick={() => onReloadNeeded()}>
        stub-reload-needed
      </button>
    </div>
  ),
}));

const PROMO = {
  promotion_id: 'P1',
  promotion_type: 'SMART',
  status: 'candidate',
  name: 'Smart',
  price: 100,
};

describe('MlaPromocionesPanel — re-read after a write attempt', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [PROMO] } });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function mountPanel() {
    render(<MlaPromocionesPanel mla="MLA1" promosCacheRef={{ current: new Map() }} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    screen.getByText('stub-applied');
    promocionesAPI.getPromocionesItem.mockClear();
  }

  it.each([['stub-applied'], ['stub-reload-needed']])('%s schedules the mirror re-reads', async (label) => {
    await mountPanel();

    await act(async () => {
      screen.getByText(label).click();
    });
    expect(promocionesAPI.getPromocionesItem).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(2);
  });
});
