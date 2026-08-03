import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import { promocionesAPI } from '../../services/api';
import { usePromoFilterStore } from '../../store/promoFilterStore';

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    getPromocionesItem: vi.fn(),
    postPromocionItem: vi.fn(),
    refreshItemPromociones: vi.fn(),
  },
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: () => true,
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

function renderPanel(props = {}) {
  const promosCacheRef = { current: new Map() };
  return render(<MlaPromocionesPanel mla="MLA001" promosCacheRef={promosCacheRef} {...props} />);
}

describe('MlaPromocionesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
  });

  it('shows a loading state while the fetch is in flight', async () => {
    let resolveFetch;
    promocionesAPI.getPromocionesItem.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    renderPanel();
    expect(screen.getByText(/cargando promociones/i)).toBeInTheDocument();

    resolveFetch({ data: { promotions: [] } });
    await waitFor(() => expect(screen.queryByText(/cargando promociones/i)).not.toBeInTheDocument());
  });

  it('shows the suggested price for candidate promos whose price is 0', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'C1',
            promotion_type: 'SELLER_CAMPAIGN',
            name: 'Campaign',
            price: 0,
            suggested_discounted_price: 999,
            original_price: 1200,
            payload: {},
          },
        ],
      },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText('Campaign')).toBeInTheDocument());
    // Candidate promo: shows the price it WOULD apply at (suggested), not $0.
    expect(screen.getByText('$999')).toBeInTheDocument();
    expect(screen.queryByText('$0')).not.toBeInTheDocument();
  });

  it('renders both applicable and read-only groups distinctly', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'SMART',
            name: 'Smart promo',
            price: 100,
            payload: { seller_percentage: 30, meli_percentage: 20 },
          },
          { promotion_id: 'P2', promotion_type: 'DOD', name: 'Deal of the day', price: 50 },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Smart promo')).toBeInTheDocument());
    expect(screen.getByText('Deal of the day')).toBeInTheDocument();
    expect(screen.getByText(/costo vendedor: 30%/i)).toBeInTheDocument();
    expect(screen.getByText(/cofinanciación ml: 20%/i)).toBeInTheDocument();
  });

  it('shows the seller-cost line for PRE_NEGOTIATED promos, like SMART', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'PN1',
            promotion_type: 'PRE_NEGOTIATED',
            name: 'Pre-negotiated promo',
            price: 100,
            payload: { seller_percentage: 30, meli_percentage: 20 },
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Pre-negotiated promo')).toBeInTheDocument());
    expect(screen.getByText(/costo vendedor: 30%/i)).toBeInTheDocument();
    expect(screen.getByText(/cofinanciación ml: 20%/i)).toBeInTheDocument();
  });

  it('shows a compact date range when both start_date and finish_date are present', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'D1',
            promotion_type: 'DEAL',
            name: 'Deal with dates',
            price: 80,
            start_date: '2026-07-01T00:00:00',
            finish_date: '2026-07-31T23:59:59',
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Deal with dates')).toBeInTheDocument());
    expect(screen.getByText('01/07 – 31/07')).toBeInTheDocument();
  });

  it('shows no date range when start_date or finish_date is missing', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'PRICE_DISCOUNT',
            name: 'No dates promo',
            price: 50,
            start_date: null,
            finish_date: null,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('No dates promo')).toBeInTheDocument());
    expect(screen.queryByText(/invalid date/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/–/)).not.toBeInTheDocument();
  });

  it('hides SMART seller-cost gracefully when payload is absent', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [{ promotion_id: 'P1', promotion_type: 'SMART', name: 'Smart promo', price: 100 }],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Smart promo')).toBeInTheDocument());
    expect(screen.queryByText(/costo vendedor/i)).not.toBeInTheDocument();
  });

  it('does not render an apply action for read-only types', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [{ promotion_id: 'P1', promotion_type: 'PRICE_DISCOUNT', name: 'Price discount', price: 50 }],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Price discount')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /aplicar/i })).not.toBeInTheDocument();
  });

  it('shows an enabled apply control for applicable types (FE-C)', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [{ promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal promo', price: 80 }],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Deal promo')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /^aplicar$/i })).toBeEnabled();
  });

  it('shows the backend-computed markup when nuestro_markup is a number', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'SMART',
            name: 'Smart promo',
            price: 100,
            payload: {},
            nuestro_markup: 18.5,
          },
        ],
      },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText('Smart promo')).toBeInTheDocument());
    expect(screen.getByText(/tu markup: 18\.5%/i)).toBeInTheDocument();
  });

  it('shows N/A when nuestro_markup is null', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'DEAL',
            name: 'Deal promo',
            price: 80,
            payload: {},
            nuestro_markup: null,
          },
        ],
      },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText('Deal promo')).toBeInTheDocument());
    expect(screen.getByText(/tu markup: n\/a/i)).toBeInTheDocument();
  });

  it('shows an "Aplicada" badge on promo rows with application_status active', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'SMART',
            name: 'Smart promo',
            status: 'started',
            application_status: 'active',
            price: 100,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Smart promo')).toBeInTheDocument());
    expect(screen.getByText(/^aplicada$/i)).toBeInTheDocument();
  });

  it('shows a "Programada" badge (not "Aplicada") on promo rows with application_status programmed', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'DEAL',
            name: 'Deal promo',
            status: 'started',
            application_status: 'programmed',
            price: 900,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Deal promo')).toBeInTheDocument());
    expect(screen.getByText(/^programada$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^aplicada$/i)).not.toBeInTheDocument();
  });

  it('does not show the "Aplicada" or "Programada" badge on candidate promo rows', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'DEAL',
            name: 'Deal promo',
            status: 'candidate',
            application_status: null,
            price: 80,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Deal promo')).toBeInTheDocument());
    expect(screen.queryByText(/^aplicada$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^programada$/i)).not.toBeInTheDocument();
  });

  it('marks each started row independently among multiple promos (active vs programmed)', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'SMART',
            name: 'Smart promo',
            status: 'started',
            application_status: 'programmed',
            price: 100,
          },
          {
            promotion_id: 'P2',
            promotion_type: 'DEAL',
            name: 'Deal promo',
            status: 'candidate',
            application_status: null,
            price: 80,
          },
          {
            promotion_id: 'P3',
            promotion_type: 'SELLER_CAMPAIGN',
            name: 'Campaign',
            status: 'started',
            application_status: 'active',
            price: 50,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Smart promo')).toBeInTheDocument());
    expect(screen.getAllByText(/^aplicada$/i)).toHaveLength(1);
    expect(screen.getAllByText(/^programada$/i)).toHaveLength(1);
  });

  it('shows the Desaplicar button for both active and programmed started promos', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'DEAL',
            name: 'Active promo',
            status: 'started',
            application_status: 'active',
            price: 50,
          },
          {
            promotion_id: 'P2',
            promotion_type: 'SMART',
            name: 'Programmed promo',
            status: 'started',
            application_status: 'programmed',
            price: 90,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Active promo')).toBeInTheDocument());
    expect(screen.getAllByRole('button', { name: /^desaplicar$/i })).toHaveLength(2);
  });

  it('shows an enabled Aplicar button for a candidate PRE_NEGOTIATED promo', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'PN1',
            promotion_type: 'PRE_NEGOTIATED',
            name: 'Pre-negotiated promo',
            status: 'candidate',
            price: 0,
            suggested_discounted_price: 900,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Pre-negotiated promo')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /^aplicar$/i })).toBeEnabled();
  });

  it('shows a Desaplicar button for a started PRE_NEGOTIATED promo', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'PN1',
            promotion_type: 'PRE_NEGOTIATED',
            name: 'Pre-negotiated promo',
            status: 'started',
            application_status: 'active',
            price: 900,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Pre-negotiated promo')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /^desaplicar$/i })).toBeEnabled();
  });

  it('shows an "En espera" badge for a pending promo (REQ-4), mutually exclusive with Aplicada/Programada', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'SMART',
            name: 'Smart promo',
            status: 'pending',
            application_status: 'pending',
            price: 100,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Smart promo')).toBeInTheDocument());
    expect(screen.getByText(/^en espera$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^aplicada$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^programada$/i)).not.toBeInTheDocument();
  });

  it('shows co-funded % fields and an enabled Aplicar for a candidate PRICE_MATCHING promo (REQ-7)', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'PM1',
            promotion_type: 'PRICE_MATCHING',
            name: 'Price matching promo',
            status: 'candidate',
            price: 0,
            suggested_discounted_price: 900,
            payload: { seller_percentage: 30, meli_percentage: 20 },
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Price matching promo')).toBeInTheDocument());
    expect(screen.getByText(/costo vendedor: 30%/i)).toBeInTheDocument();
    expect(screen.getByText(/cofinanciación ml: 20%/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^aplicar$/i })).toBeEnabled();
  });

  it('shows a Desaplicar button for a pending PRICE_MATCHING promo (REQ-7/REQ-6)', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'PM1',
            promotion_type: 'PRICE_MATCHING',
            name: 'Price matching promo',
            status: 'pending',
            application_status: 'pending',
            price: 900,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Price matching promo')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /^desaplicar$/i })).toBeEnabled();
  });

  it('never renders an apply control for PRICE_MATCHING_MELI_ALL, in any status (REQ-9 guard)', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'PMA1',
            promotion_type: 'PRICE_MATCHING_MELI_ALL',
            name: 'Price matching meli all',
            status: 'started',
            price: 900,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Price matching meli all')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /^aplicar$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^desaplicar$/i })).not.toBeInTheDocument();
  });

  it('colors the promo-row markup using the shared markup-color thresholds (ADD-1)', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P1',
            promotion_type: 'DEAL',
            name: 'Positive markup promo',
            price: 80,
            nuestro_markup: 25,
          },
          {
            promotion_id: 'P2',
            promotion_type: 'DEAL',
            name: 'Negative markup promo',
            price: 80,
            nuestro_markup: -5,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Positive markup promo')).toBeInTheDocument());
    const positiveMarkup = screen.getByText(/tu markup: 25\.0%/i);
    const negativeMarkup = screen.getByText(/tu markup: -5\.0%/i);
    expect(positiveMarkup).toHaveStyle({ color: 'var(--success)' });
    expect(negativeMarkup).toHaveStyle({ color: 'var(--error)' });
  });

  it('shows the promo name (not the cryptic type) as the primary label', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'C-MLA1332399',
            promotion_type: 'SELLER_CAMPAIGN',
            name: 'PREMIUM JULIO',
            price: 100,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('PREMIUM JULIO')).toBeInTheDocument());
    expect(screen.queryByText('C-MLA1332399')).not.toBeInTheDocument();
  });

  it('falls back to promotion_type then promotion_id when name is null', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          { promotion_id: 'C-MLA1332399', promotion_type: 'PRICE_DISCOUNT', name: null, price: 100 },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getAllByText('PRICE_DISCOUNT').length).toBeGreaterThan(0));
  });

  it('falls back to payload.name when top-level name is absent', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'C-MLA1332399',
            promotion_type: 'SELLER_CAMPAIGN',
            name: null,
            payload: { name: 'PREMIUM JULIO (payload)' },
            price: 100,
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('PREMIUM JULIO (payload)')).toBeInTheDocument());
  });

  it('shows an error state distinct from empty', async () => {
    promocionesAPI.getPromocionesItem.mockRejectedValue(new Error('network error'));

    renderPanel();

    await waitFor(() => expect(screen.getByText(/error al cargar promociones/i)).toBeInTheDocument());
  });

  it('shows an empty state when there are zero promotions', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/sin promociones/i)).toBeInTheDocument());
  });

  it('DOES re-fetch when re-mounted with the same cached mla', async () => {
    // This used to assert the opposite. The cache existed so a collapse and
    // re-expand did not re-hit the API, and refreshes were manual because the
    // ML throttle is shared with sales-webhook processing.
    //
    // The product owner reversed that: seeing stale promotions without knowing
    // they are stale was the worse failure. So every open pulls fresh state,
    // and the cache no longer suppresses it. The old expectation is not a
    // regression here — it is the behaviour that was deliberately dropped.
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: [{ promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal promo', price: 80 }] },
    });

    const promosCacheRef = { current: new Map() };
    const { unmount } = render(<MlaPromocionesPanel mla="MLA001" promosCacheRef={promosCacheRef} />);
    await waitFor(() => expect(screen.getByText('Deal promo')).toBeInTheDocument());
    unmount();

    render(<MlaPromocionesPanel mla="MLA001" promosCacheRef={promosCacheRef} />);
    await waitFor(() => expect(screen.getByText('Deal promo')).toBeInTheDocument());

    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(2);
  });

  it('does not call reload/getPromocionesItem again after unmounting before either post-apply reload fires (~5s, ~65s)', async () => {
    vi.useFakeTimers();
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: [{ promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal promo', price: 80 }] },
    });
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'submitted' } });

    const { unmount } = renderPanel();
    // Fake timers don't stop native Promise microtasks from flushing, so
    // waitFor's polling (setInterval-based) still needs the fake clock
    // nudged; flush via act on the resolved fetcher promise instead.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText('Deal promo')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^aplicar$/i }));
    fireEvent.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    // Flush the microtask that resolves postPromocionItem and schedules the
    // two reload timers before unmounting.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);

    unmount();

    act(() => {
      vi.advanceTimersByTime(65000);
    });

    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);
    expect(consoleError).not.toHaveBeenCalled();

    consoleError.mockRestore();
    vi.useRealTimers();
  });

  it('schedules TWO reloads after a state-changing apply: ~5s (fast) and ~65s (slow/retry), and never calls a FE refresh endpoint', async () => {
    vi.useFakeTimers();

    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: [{ promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal promo', price: 80 }] },
    });
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'submitted' } });

    renderPanel();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    fireEvent.click(screen.getByRole('button', { name: /^aplicar$/i }));
    fireEvent.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);

    // Nothing before ~5s.
    await act(async () => {
      vi.advanceTimersByTime(4999);
    });
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);

    // First reload fires at ~5s.
    await act(async () => {
      vi.advanceTimersByTime(2);
      await Promise.resolve();
    });
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(2);

    // Nothing new until ~65s.
    await act(async () => {
      vi.advanceTimersByTime(59000);
    });
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(2);

    // Second reload fires at ~65s total.
    await act(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
    });
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(3);

    // The FE never calls a refresh endpoint itself — server owns refresh.
    expect(promocionesAPI.getPromocionesItem).not.toHaveBeenCalledWith(expect.stringContaining('/refresh'));
    const calledUrls = Object.values(promocionesAPI)
      .flatMap((fn) => (fn.mock ? fn.mock.calls : []))
      .flat();
    expect(calledUrls.some((arg) => typeof arg === 'string' && arg.includes('refresh'))).toBe(false);

    vi.useRealTimers();
  });

  describe('global promo-type filter', () => {
    const promotions = [
      { promotion_id: 'P1', promotion_type: 'SMART', name: 'Smart promo', price: 100 },
      { promotion_id: 'P2', promotion_type: 'DEAL', name: 'Deal promo', price: 80 },
    ];

    it('shows all promos when selectedTypes is empty', async () => {
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions } });

      renderPanel();

      await waitFor(() => expect(screen.getByText('Smart promo')).toBeInTheDocument());
      expect(screen.getByText('Deal promo')).toBeInTheDocument();
    });

    it('shows only promos matching selectedTypes', async () => {
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions } });
      usePromoFilterStore.setState({ selectedTypes: ['SMART'] });

      renderPanel();

      await waitFor(() => expect(screen.getByText('Smart promo')).toBeInTheDocument());
      expect(screen.queryByText('Deal promo')).not.toBeInTheDocument();
    });

    it('shows the empty-filter message when everything is filtered out', async () => {
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions } });
      usePromoFilterStore.setState({ selectedTypes: ['LIGHTNING'] });

      renderPanel();

      await waitFor(() => expect(screen.getByText(/sin promos del tipo filtrado/i)).toBeInTheDocument());
      expect(screen.queryByText('Smart promo')).not.toBeInTheDocument();
    });
  });

  describe('name-level filter (composed with the type-level filter)', () => {
    const namedPromotions = [
      { promotion_id: 'P1', promotion_type: 'DEAL', name: '2x1', price: 80 },
      { promotion_id: 'P2', promotion_type: 'DEAL', name: '3x2', price: 90 },
      { promotion_id: 'P3', promotion_type: 'SMART', name: 'Promo Smart', price: 100 },
    ];

    it('shows every promo when selectedNames is empty (nothing selected -> show all)', async () => {
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: namedPromotions } });

      renderPanel();

      await waitFor(() => expect(screen.getByText('2x1')).toBeInTheDocument());
      expect(screen.getByText('3x2')).toBeInTheDocument();
      expect(screen.getByText('Promo Smart')).toBeInTheDocument();
    });

    it('narrows within a permitted type by the selected name', async () => {
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: namedPromotions } });
      usePromoFilterStore.setState({ selectedNames: { DEAL: ['2x1'] } });

      renderPanel();

      await waitFor(() => expect(screen.getByText('2x1')).toBeInTheDocument());
      expect(screen.queryByText('3x2')).not.toBeInTheDocument();
      expect(screen.getByText('Promo Smart')).toBeInTheDocument();
    });

    it('type-level exclusion wins over a stale name selection', async () => {
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: namedPromotions } });
      usePromoFilterStore.setState({ selectedTypes: ['SMART'], selectedNames: { DEAL: ['2x1'] } });

      renderPanel();

      await waitFor(() => expect(screen.getByText('Promo Smart')).toBeInTheDocument());
      expect(screen.queryByText('2x1')).not.toBeInTheDocument();
    });

    it('persists the name selection across unmount/remount of the same MLA (collapse/re-expand)', async () => {
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: namedPromotions } });
      usePromoFilterStore.setState({ selectedNames: { DEAL: ['2x1'] } });

      const promosCacheRef = { current: new Map() };
      const { unmount } = render(<MlaPromocionesPanel mla="MLA001" promosCacheRef={promosCacheRef} />);
      await waitFor(() => expect(screen.getByText('2x1')).toBeInTheDocument());
      expect(screen.queryByText('3x2')).not.toBeInTheDocument();
      unmount();

      render(<MlaPromocionesPanel mla="MLA001" promosCacheRef={promosCacheRef} />);
      await waitFor(() => expect(screen.getByText('2x1')).toBeInTheDocument());
      expect(screen.queryByText('3x2')).not.toBeInTheDocument();
    });
  });
});

describe('MlaPromocionesPanel — auto-refresh on open', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('asks the server for a fresh pull from ML before showing anything', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promociones: [] } });

    render(<MlaPromocionesPanel mla="MLA_AUTO" promosCacheRef={{ current: new Map() }} />);

    await waitFor(() => expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledWith('MLA_AUTO'));
    await waitFor(() => expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledWith('MLA_AUTO'));
  });

  it('refreshes again on a later open instead of serving the cached mirror', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promociones: [] } });
    const cacheRef = { current: new Map() };

    const first = render(<MlaPromocionesPanel mla="MLA_AUTO" promosCacheRef={cacheRef} />);
    await waitFor(() => expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(1));
    first.unmount();

    render(<MlaPromocionesPanel mla="MLA_AUTO" promosCacheRef={cacheRef} />);

    await waitFor(() => expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(2));
  });

  it('still shows the mirror when the refresh itself fails', async () => {
    promocionesAPI.refreshItemPromociones.mockRejectedValue(new Error('ML no responde'));
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promociones: [] } });

    render(<MlaPromocionesPanel mla="MLA_AUTO" promosCacheRef={{ current: new Map() }} />);

    // A failed refresh must degrade to the stored mirror, not blank the panel:
    // stale data plus a working screen beats an error and nothing.
    await waitFor(() => expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledWith('MLA_AUTO'));
  });
});
