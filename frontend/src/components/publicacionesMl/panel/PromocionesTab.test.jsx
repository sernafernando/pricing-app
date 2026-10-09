/**
 * Promociones tab (publicaciones-ml-vista P13c): the promotions of one
 * publication, through the same panel the Productos page uses. The tab only
 * decides WHEN it mounts and WHICH global state it must ignore; reading,
 * pulling and applying stay in `MlaPromocionesPanel`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromocionesTab from './PromocionesTab';
import { promocionesAPI } from '../../../services/api';
import { usePromoFilterStore } from '../../../store/promoFilterStore';
import { readDetail } from './detailModel';
import { DETAIL_RESPONSE } from '../../../test/visual/publicacionesMlFixtures';

vi.mock('../../../services/api', () => ({
  promocionesAPI: {
    getPromocionesItem: vi.fn(),
    refreshItemPromociones: vi.fn(),
    postPromocionItem: vi.fn(),
    deletePromocionItem: vi.fn(),
    confirmarSinPromosML: vi.fn(() => Promise.resolve({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } })),
  },
}));

const permisosMock = vi.hoisted(() => ({ denied: [] }));
vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => !permisosMock.denied.includes(permiso),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

// Same shape as the per-item mirror read in MlaPromocionesPanel.test.jsx.
const PROMOTIONS = [
  { promotion_id: 'P1', promotion_type: 'SMART', name: 'Smart promo', price: 100, payload: { seller_percentage: 30, meli_percentage: 20 } },
  { promotion_id: 'P2', promotion_type: 'DOD', name: 'Deal of the day', price: 50 },
];

const renderTab = (itemId = 'MLA1100000001', props = {}) => {
  const detail = readDetail(DETAIL_RESPONSE);
  return render(<PromocionesTab detail={detail} itemId={itemId} canSeeMargin={false} dataState={null} {...props} />);
};

beforeEach(() => {
  vi.clearAllMocks();
  permisosMock.denied = [];
  usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
  promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: PROMOTIONS } });
  promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
});

describe('reading the promotions', () => {
  it('pulls from ML on opening, then reads the mirror of the selected publication', async () => {
    renderTab();
    expect(await screen.findByText('Smart promo')).toBeInTheDocument();
    expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledWith('MLA1100000001');
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledWith('MLA1100000001');
    expect(promocionesAPI.refreshItemPromociones.mock.invocationCallOrder[0]).toBeLessThan(promocionesAPI.getPromocionesItem.mock.invocationCallOrder[0]);
  });

  it('a view-only user (no promos.escribir) still reads the promotions and sees the apply control disabled', async () => {
    permisosMock.denied = ['promos.escribir'];
    renderTab();
    expect(await screen.findByText('Smart promo')).toBeInTheDocument();
    expect(screen.getAllByText('Sin permiso').length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /aplicar/i })).not.toBeInTheDocument();
  });

  it('asks again when the selected publication changes, never showing the previous one', async () => {
    const { rerender } = renderTab('MLA1100000001');
    await screen.findByText('Smart promo');
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [{ promotion_id: 'P9', promotion_type: 'DEAL', name: 'Other item promo', price: 10 }] } });
    rerender(<PromocionesTab detail={readDetail(DETAIL_RESPONSE)} itemId="MLA1100000002" canSeeMargin={false} dataState={null} />);
    expect(await screen.findByText('Other item promo')).toBeInTheDocument();
    expect(screen.queryByText('Smart promo')).not.toBeInTheDocument();
    expect(promocionesAPI.getPromocionesItem).toHaveBeenLastCalledWith('MLA1100000002');
  });
});

describe('the Promociones page filter', () => {
  it('does not leak into the tab: a type or name filter left in the store hides nothing here', async () => {
    usePromoFilterStore.setState({ selectedTypes: ['LIGHTNING'], selectedNames: { DEAL: ['2x1'] } });
    renderTab();
    await waitFor(() => expect(screen.getByText('Smart promo')).toBeInTheDocument());
    expect(screen.getByText('Deal of the day')).toBeInTheDocument();
    expect(screen.queryByText(/sin promos del tipo filtrado/i)).not.toBeInTheDocument();
  });

  it('leaves the global filter untouched', async () => {
    usePromoFilterStore.setState({ selectedTypes: ['LIGHTNING'] });
    renderTab();
    await screen.findByText('Smart promo');
    expect(usePromoFilterStore.getState().selectedTypes).toEqual(['LIGHTNING']);
  });
});

describe('after a write', () => {
  const DEAL = { promotion_id: 'D1', promotion_type: 'DEAL', name: 'Deal promo', price: 80, status: 'candidate' };

  it('tells the panel once an apply went through, so price and markup can be re-read', async () => {
    const user = userEvent.setup();
    const onPromoApplied = vi.fn();
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [DEAL] } });
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    renderTab('MLA1100000001', { onPromoApplied });
    await user.click(await screen.findByRole('button', { name: /^aplicar$/i }));
    expect(onPromoApplied).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));
    await waitFor(() => expect(onPromoApplied).toHaveBeenCalledTimes(1));
  });

  it('tells the panel once a removal went through', async () => {
    const user = userEvent.setup();
    const onPromoApplied = vi.fn();
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [{ ...DEAL, status: 'started' }] } });
    promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'reconciled_applied' } });
    renderTab('MLA1100000001', { onPromoApplied });
    await user.click(await screen.findByRole('button', { name: /^desaplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));
    await waitFor(() => expect(onPromoApplied).toHaveBeenCalledTimes(1));
  });
});
