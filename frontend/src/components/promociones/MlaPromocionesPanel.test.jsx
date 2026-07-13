import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import { promocionesAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    getPromocionesItem: vi.fn(),
    postPromocionItem: vi.fn(),
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

  it('does not re-fetch when re-mounted with the same cached mla', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: [{ promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal promo', price: 80 }] },
    });

    const promosCacheRef = { current: new Map() };
    const { unmount } = render(<MlaPromocionesPanel mla="MLA001" promosCacheRef={promosCacheRef} />);
    await waitFor(() => expect(screen.getByText('Deal promo')).toBeInTheDocument());
    unmount();

    render(<MlaPromocionesPanel mla="MLA001" promosCacheRef={promosCacheRef} />);
    await waitFor(() => expect(screen.getByText('Deal promo')).toBeInTheDocument());

    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);
  });

  it('does not call reload/getPromocionesItem again after unmounting before the 4s post-apply reload fires', async () => {
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
    // 4s reload timer before unmounting.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);

    unmount();

    act(() => {
      vi.advanceTimersByTime(4000);
    });

    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);
    expect(consoleError).not.toHaveBeenCalled();

    consoleError.mockRestore();
    vi.useRealTimers();
  });
});
