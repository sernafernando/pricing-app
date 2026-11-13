/**
 * Promociones tab (publicaciones-ml-vista P13c): the promotions of one
 * publication, through the same panel the Productos page uses. The tab only
 * decides WHEN it mounts and WHICH global state it must ignore; reading,
 * pulling and applying stay in `MlaPromocionesPanel`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromocionesTab from './PromocionesTab';
import { resetPromoPulls } from '../../promociones/promoPullTtl';
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
    getCompetenciaCatalogo: vi.fn(() =>
      Promise.resolve({ data: { mla: 'MLA1100000001', fetch_status: 'never', undercutting: [], same_bucket: [] } }),
    ),
    refreshCompetenciaCatalogo: vi.fn(),
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
  // The pull TTL lives at module scope, on purpose: every test starts with no MLA pulled.
  resetPromoPulls();
  permisosMock.denied = [];
  usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
  promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: PROMOTIONS } });
  promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
});

describe('reading the promotions', () => {
  it('shows the mirror of the selected publication first, then pulls from ML in the background', async () => {
    renderTab();
    expect(await screen.findByText('Smart promo')).toBeInTheDocument();
    await waitFor(() => expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledWith('MLA1100000001'));
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledWith('MLA1100000001');
    expect(promocionesAPI.getPromocionesItem.mock.invocationCallOrder[0]).toBeLessThan(promocionesAPI.refreshItemPromociones.mock.invocationCallOrder[0]);
  });

  it('a view-only user (no promos.escribir) still reads the promotions and sees the apply control disabled', async () => {
    permisosMock.denied = ['promos.escribir'];
    renderTab();
    expect(await screen.findByText('Smart promo')).toBeInTheDocument();
    // The apply controls appear once the background pull settles.
    expect((await screen.findAllByText('Sin permiso')).length).toBeGreaterThan(0);
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

describe('the promo filter (one setting for the user, shared with Productos)', () => {
  it('applies a type or name filter left in the store and says so, so no promotion looks missing', async () => {
    usePromoFilterStore.setState({ selectedTypes: ['SMART', 'DEAL'], selectedNames: { SMART: ['Smart promo'], DEAL: ['2x1', '3x2'] } });
    renderTab();
    expect(await screen.findByText('Smart promo')).toBeInTheDocument();
    expect(screen.queryByText('Deal of the day')).not.toBeInTheDocument();
    expect(screen.getByText('Filtro: 2 tipos · 3 nombres')).toBeInTheDocument();
  });

  it('counts only the names that filter: a name kept for a type that is not chosen is left out', async () => {
    usePromoFilterStore.setState({ selectedTypes: ['SMART'], selectedNames: { DOD: ['Deal of the day'] } });
    renderTab();
    expect(await screen.findByText('Smart promo')).toBeInTheDocument();
    expect(screen.getByText('Filtro: 1 tipo')).toBeInTheDocument();
  });

  it('shows no summary and hides nothing while no filter is set', async () => {
    renderTab();
    expect(await screen.findByText('Smart promo')).toBeInTheDocument();
    expect(screen.getByText('Deal of the day')).toBeInTheDocument();
    expect(screen.queryByText(/^Filtro:/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Quitar filtro' })).not.toBeInTheDocument();
  });

  it('is set from the tab header: the chips of the Productos filter bar narrow the list', async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText('Deal of the day');
    const toggle = screen.getByRole('button', { name: 'Filtrar promos' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    // The toggle already names the filter: the chip row does not repeat "Filtrar promos:".
    expect(screen.queryByText('Filtrar promos:')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Smart' }));
    expect(screen.queryByText('Deal of the day')).not.toBeInTheDocument();
    expect(screen.getByText('Smart promo')).toBeInTheDocument();
    expect(screen.getByText('Filtro: 1 tipo')).toBeInTheDocument();
    expect(usePromoFilterStore.getState().selectedTypes).toEqual(['SMART']);
  });

  it('keeps applying when the selected publication changes', async () => {
    usePromoFilterStore.setState({ selectedTypes: ['DOD'] });
    const { rerender } = renderTab('MLA1100000001');
    expect(await screen.findByText('Deal of the day')).toBeInTheDocument();
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          { promotion_id: 'P8', promotion_type: 'SMART', name: 'Other smart', price: 10 },
          { promotion_id: 'P9', promotion_type: 'DOD', name: 'Other deal', price: 10 },
        ],
      },
    });
    rerender(<PromocionesTab detail={readDetail(DETAIL_RESPONSE)} itemId="MLA1100000002" canSeeMargin={false} dataState={null} />);
    expect(await screen.findByText('Other deal')).toBeInTheDocument();
    expect(screen.queryByText('Other smart')).not.toBeInTheDocument();
    expect(screen.getByText('Filtro: 1 tipo')).toBeInTheDocument();
    expect(usePromoFilterStore.getState().selectedTypes).toEqual(['DOD']);
  });

  it('"Quitar filtro" clears it in one click and every promotion shows again', async () => {
    const user = userEvent.setup();
    usePromoFilterStore.setState({ selectedTypes: ['SMART'], selectedNames: { SMART: ['Smart promo'] } });
    renderTab();
    await screen.findByText('Smart promo');
    expect(screen.queryByText('Deal of the day')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Quitar filtro' }));
    expect(await screen.findByText('Deal of the day')).toBeInTheDocument();
    expect(screen.queryByText(/^Filtro:/)).not.toBeInTheDocument();
    expect(usePromoFilterStore.getState()).toMatchObject({ selectedTypes: [], selectedNames: {} });
  });

  it('lists the names of the promotions loaded here in the "Nombres" modal', async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText('Deal of the day');
    await user.click(screen.getByRole('button', { name: 'Filtrar promos' }));
    await user.click(screen.getByRole('button', { name: 'Nombres' }));
    expect(await screen.findByText('Filtrar promos por nombre')).toBeInTheDocument();
    expect(screen.getByLabelText('Smart promo')).toBeInTheDocument();
    expect(screen.getByLabelText('Deal of the day')).toBeInTheDocument();
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

  it('tells the panel again when the mirror is re-read at ~5s and ~65s, because the new price lands late', async () => {
    const onPromoApplied = vi.fn();
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [DEAL] } });
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderTab('MLA1100000001', { onPromoApplied });
      await user.click(await screen.findByRole('button', { name: /^aplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));
      await waitFor(() => expect(onPromoApplied).toHaveBeenCalledTimes(1));
      await vi.advanceTimersByTimeAsync(5000);
      expect(onPromoApplied).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(60000);
      expect(onPromoApplied).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
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

describe('the pull TTL (5 minutes per MLA)', () => {
  const FIVE_MINUTES = 5 * 60 * 1000;
  const openAndClose = async (itemId = 'MLA1100000001') => {
    const view = renderTab(itemId);
    await screen.findByText('Smart promo');
    await waitFor(() => expect(screen.queryByText(/actualizando/i)).not.toBeInTheDocument());
    view.unmount();
  };

  it('does not pull again an MLA it pulled less than 5 minutes ago, even after a remount, and pulls again after', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(1_000_000);
    try {
      await openAndClose();
      expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(1);
      now.mockReturnValue(1_000_000 + FIVE_MINUTES - 1);
      const readsBefore = promocionesAPI.getPromocionesItem.mock.calls.length;
      await openAndClose();
      expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(1);
      // The mirror is still read on every open.
      expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(readsBefore + 1);
      now.mockReturnValue(1_000_000 + FIVE_MINUTES);
      await openAndClose();
      expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(2);
    } finally {
      now.mockRestore();
    }
  });

  it('keeps one TTL per MLA: another publication still pulls', async () => {
    await openAndClose('MLA1100000001');
    await openAndClose('MLA1100000002');
    expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(2);
  });

  it('a failed pull starts no TTL: the next open pulls again', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: false, motivo: 'proxy caído' } });
    await openAndClose();
    await openAndClose();
    expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(2);
  });

  it('a pull cancelled by closing the tab starts no TTL: the next open pulls again', async () => {
    let answer;
    promocionesAPI.refreshItemPromociones.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    const view = renderTab();
    await waitFor(() => expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(1));
    view.unmount();
    answer({ data: { ok: true } });
    // Let the abandoned pull run to its end (its re-read of the mirror) before opening again.
    await waitFor(() => expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(2));
    await openAndClose();
    expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(2);
  });

  it('an apply clears the MLA from the TTL: the next open pulls again', async () => {
    const user = userEvent.setup();
    const DEAL = { promotion_id: 'D1', promotion_type: 'DEAL', name: 'Deal promo', price: 80, status: 'candidate' };
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [DEAL] } });
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    const view = renderTab();
    await user.click(await screen.findByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));
    await waitFor(() => expect(promocionesAPI.postPromocionItem).toHaveBeenCalled());
    view.unmount();
    renderTab();
    await waitFor(() => expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(2));
  });

  it('a removal clears the MLA from the TTL: the next open pulls again', async () => {
    const user = userEvent.setup();
    const STARTED = { promotion_id: 'D1', promotion_type: 'DEAL', name: 'Deal promo', price: 80, status: 'started' };
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [STARTED] } });
    promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'reconciled_applied' } });
    const view = renderTab();
    await user.click(await screen.findByRole('button', { name: /^desaplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));
    await waitFor(() => expect(promocionesAPI.deletePromocionItem).toHaveBeenCalled());
    view.unmount();
    renderTab();
    await waitFor(() => expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(2));
  });
});

// S3 (owner: "en promos hay promos que no son promos sino cupones y no se pueden activar desde ahí").
// The coupon is ML's own object as captured in
// backend/tests/fixtures/ml_publications/history_events_MLA1402898289_20261016.json; the mirror keeps ML's object
// as `payload`.
const COUPON_ML = {
  id: 'C-MLA1713876',
  name: 'Cupón de recompra',
  type: 'SELLER_COUPON_CAMPAIGN',
  price: 0,
  status: 'candidate',
  sub_type: 'FIXED_PERCENTAGE',
  start_date: '2026-10-10T00:00:00',
  finish_date: '2026-10-31T23:59:59',
  original_price: 91193,
  fixed_percentage: 10,
};
const SECTIONED = [
  { promotion_id: 'P-INFO', promotion_type: 'DOD', name: 'Deal of the day', status: 'candidate', price: 50 },
  {
    promotion_id: COUPON_ML.id,
    promotion_type: COUPON_ML.type,
    sub_type: COUPON_ML.sub_type,
    status: 'candidate',
    price: 0,
    original_price: COUPON_ML.original_price,
    name: COUPON_ML.name,
    start_date: COUPON_ML.start_date,
    finish_date: COUPON_ML.finish_date,
    payload: COUPON_ML,
  },
  { promotion_id: 'P-AVAIL', promotion_type: 'DEAL', name: 'Deal disponible', status: 'candidate', price: 0, suggested_discounted_price: 90, nuestro_markup: 12.5 },
  { promotion_id: 'P-PROG', promotion_type: 'SELLER_CAMPAIGN', name: 'Campaña programada', status: 'started', application_status: 'programmed', price: 95 },
  { promotion_id: 'P-ACTIVE', promotion_type: 'SMART', name: 'Smart activa', status: 'started', application_status: 'active', price: 80, nuestro_markup: 20 },
  // A coupon whose row is not the captured shape: shown read-only, nothing guessed.
  { promotion_id: 'C-OTHER', promotion_type: 'SELLER_COUPON_CAMPAIGN', name: 'Cupón sin detalle', payload: {} },
];

describe('sections (S3)', () => {
  beforeEach(() => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: SECTIONED } });
  });
  const section = (name) => screen.getByRole('region', { name });

  it('orders the promotions: Activa ahora, Disponibles para activar, Otras promociones, and the coupons last', async () => {
    renderTab();
    await screen.findByText('Smart activa');
    expect(screen.getAllByRole('region').map((region) => region.getAttribute('aria-label'))).toEqual([
      'Activa ahora',
      'Disponibles para activar',
      'Otras promociones',
      'Cupones',
    ]);
    expect(section('Activa ahora')).toHaveTextContent('Smart activa');
    expect(section('Otras promociones')).toHaveTextContent('Campaña programada');
    expect(section('Otras promociones')).toHaveTextContent('Deal of the day');
  });

  it('shows each available promotion with the markup it would leave and its apply control', async () => {
    renderTab();
    await screen.findByText('Deal disponible');
    const available = section('Disponibles para activar');
    expect(available).toHaveTextContent('Deal disponible');
    expect(available).toHaveTextContent('Tu markup: 12.5%');
    expect(await within(available).findByRole('button', { name: /^aplicar$/i })).toBeInTheDocument();
    expect(available).not.toHaveTextContent('Smart activa');
  });

  it('shows the coupons apart, with no apply control and only a link to Mercado Libre', async () => {
    renderTab();
    await screen.findByText('Cupón de recompra');
    // Wait for the background pull: the apply controls show only after it.
    await within(section('Disponibles para activar')).findByRole('button', { name: /^aplicar$/i });
    const coupons = section('Cupones');
    expect(within(coupons).queryAllByRole('button')).toEqual([]);
    expect(coupons).toHaveTextContent('Cupón de recompra');
    expect(coupons).toHaveTextContent('10% de descuento');
    expect(coupons).not.toHaveTextContent('Tu markup');
    const links = within(coupons).getAllByRole('link', { name: 'Ver promociones en Mercado Libre' });
    expect(links[0]).toHaveAttribute('href', 'https://vendedores.mercadolibre.com.ar/publicaciones/listado/promos?page=1&search=1100000001');
    // The other shape: its name, read-only, no percentage made up.
    expect(coupons).toHaveTextContent('Cupón sin detalle');
    expect(coupons.querySelectorAll('li')).toHaveLength(2);
    expect(coupons.textContent.match(/% de descuento/g)).toHaveLength(1);
  });

  it('keeps a programmed or waiting promotion out of the available ones, whatever its ML status', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          { promotion_id: 'P-WAIT', promotion_type: 'DEAL', name: 'Deal en espera', status: 'candidate', application_status: 'pending', price: 90 },
          { promotion_id: 'P-LATER', promotion_type: 'SMART', name: 'Smart programada', status: 'candidate', application_status: 'programmed', price: 85 },
        ],
      },
    });
    renderTab();
    await screen.findByText('Deal en espera');
    expect(screen.queryByRole('region', { name: 'Disponibles para activar' })).not.toBeInTheDocument();
    expect(section('Otras promociones')).toHaveTextContent('Deal en espera');
    expect(section('Otras promociones')).toHaveTextContent('Smart programada');
  });

  it('leaves out a section with nothing in it', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: SECTIONED.filter((promo) => promo.promotion_type !== 'SELLER_COUPON_CAMPAIGN') } });
    renderTab();
    await screen.findByText('Smart activa');
    expect(screen.queryByRole('region', { name: 'Cupones' })).not.toBeInTheDocument();
  });
});

describe('Ver competencia (catalog ranking column)', () => {
  it('hides Ver competencia when the publication is not a catalog listing', async () => {
    renderTab();
    await screen.findByText('Smart promo');
    expect(screen.queryByRole('button', { name: /ver competencia/i })).not.toBeInTheDocument();
  });

  it('shows Ver competencia for a catalog listing and opens the ranking when open', async () => {
    const onCompetenciaOpenChange = vi.fn();
    const detail = readDetail(DETAIL_RESPONSE);
    detail.row = { ...detail.row, catalog_listing: true };
    render(
      <PromocionesTab
        detail={detail}
        itemId="MLA1100000001"
        canSeeMargin={false}
        dataState={null}
        competenciaOpen={false}
        onCompetenciaOpenChange={onCompetenciaOpenChange}
      />,
    );
    await screen.findByText('Smart promo');
    await userEvent.click(screen.getByRole('button', { name: /ver competencia/i }));
    expect(onCompetenciaOpenChange).toHaveBeenCalledWith(true);

    render(
      <PromocionesTab
        detail={detail}
        itemId="MLA1100000001"
        canSeeMargin={false}
        dataState={null}
        competenciaOpen
        onCompetenciaOpenChange={onCompetenciaOpenChange}
      />,
    );
    expect(screen.getByRole('button', { name: /ocultar competencia/i })).toBeInTheDocument();
    expect(screen.getByText('Competencia del catálogo')).toBeInTheDocument();
    await waitFor(() => expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalled());
  });

  it('tells the page when the ranking is on screen, and that it is off once the tab goes', async () => {
    const onCompetenciaShownChange = vi.fn();
    const detail = readDetail(DETAIL_RESPONSE);
    detail.row = { ...detail.row, catalog_listing: true };
    const { unmount } = render(
      <PromocionesTab
        detail={detail}
        itemId="MLA1100000001"
        canSeeMargin={false}
        dataState={null}
        competenciaOpen
        onCompetenciaShownChange={onCompetenciaShownChange}
      />,
    );
    await screen.findByText('Smart promo');
    expect(onCompetenciaShownChange).toHaveBeenLastCalledWith(true);
    unmount();
    expect(onCompetenciaShownChange).toHaveBeenLastCalledWith(false);
  });

  it('a listing outside the catalog never shows the ranking, even with it open', async () => {
    const onCompetenciaShownChange = vi.fn();
    render(
      <PromocionesTab
        detail={readDetail(DETAIL_RESPONSE)}
        itemId="MLA1100000001"
        canSeeMargin={false}
        dataState={null}
        competenciaOpen
        onCompetenciaShownChange={onCompetenciaShownChange}
      />,
    );
    await screen.findByText('Smart promo');
    expect(screen.queryByText('Competencia del catálogo')).not.toBeInTheDocument();
    expect(onCompetenciaShownChange).not.toHaveBeenCalledWith(true);
  });
});
