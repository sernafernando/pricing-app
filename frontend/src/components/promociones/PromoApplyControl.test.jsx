import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent as fireEventClick } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromoApplyControl from './PromoApplyControl';
import { promocionesAPI } from '../../services/api';

const mockTienePermiso = vi.fn(() => true);

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    postPromocionItem: vi.fn(),
    deletePromocionItem: vi.fn(),
    getMarkupParaPrecio: vi.fn(),
  },
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => mockTienePermiso(codigo),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

function dealPromo(overrides = {}) {
  return { promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal promo', price: 80, ...overrides };
}

describe('PromoApplyControl', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  it('is disabled ("sin permiso") when the user lacks promos.escribir', () => {
    mockTienePermiso.mockReturnValue(false);
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    expect(screen.getByText(/sin permiso/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^aplicar$/i })).not.toBeInTheDocument();
  });

  it('is disabled for a non-writable promotion type (e.g. DOD)', () => {
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo({ promotion_type: 'DOD' })} />);

    expect(screen.getByText(/lo maneja ml/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^aplicar$/i })).not.toBeInTheDocument();
  });

  it('requires an explicit confirmation step before posting', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
    expect(screen.getByText(/¿aplicar esta promoción\?/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));
    await waitFor(() => expect(promocionesAPI.postPromocionItem).toHaveBeenCalledTimes(1));
    expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA1', {
      promotion_id: 'P1',
      promotion_type: 'DEAL',
    });
  });

  it('cancelling the confirm step does not post', async () => {
    const user = userEvent.setup();
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /cancelar/i }));

    expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /^aplicar$/i })).toBeInTheDocument();
  });

  it('shows submitted feedback without claiming a confirmed success', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/puede tardar en reflejarse/i)).toBeInTheDocument());
  });

  it('shows ambiguous (202) feedback and does not auto-retry', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'ambiguous' } });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/estado por confirmar/i)).toBeInTheDocument());
    expect(promocionesAPI.postPromocionItem).toHaveBeenCalledTimes(1);
  });

  it('shows rejected feedback on a 422 response', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockRejectedValue({
      response: { status: 422, data: { detail: 'Precio fuera de rango' } },
    });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/precio fuera de rango/i)).toBeInTheDocument());
    expect(promocionesAPI.postPromocionItem).toHaveBeenCalledTimes(1);
  });

  it('shows a kill-switch "disabled" message on a 403 with disabled status', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: false, status: 'disabled' } });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/escritura deshabilitada/i)).toBeInTheDocument());
  });

  it('flips to "no disponible" when the write endpoint responds 404 and does not retry automatically', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockRejectedValue({ response: { status: 404 } });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/aplicar no disponible/i)).toBeInTheDocument());
    expect(promocionesAPI.postPromocionItem).toHaveBeenCalledTimes(1);
  });

  it('shows a SUCCESS message for reconciled_applied (the only true-success path)', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: { submitted: true, status: 'reconciled_applied' },
    });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/promoción aplicada/i)).toBeInTheDocument());
    expect(screen.queryByText(/verificá en ml/i)).not.toBeInTheDocument();
  });

  it('shows a WARNING (not success) for reconciled_not_applied', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: { submitted: true, status: 'reconciled_not_applied' },
    });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/aún no reflejado.*verificá en ml/i)).toBeInTheDocument());
    expect(screen.queryByText(/^promoción aplicada$/i)).not.toBeInTheDocument();
  });

  it('shows the unsupported-type message for rejected_unsupported_type, not success', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: { submitted: false, status: 'rejected_unsupported_type' },
    });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/tipo de promoción no soportado/i)).toBeInTheDocument());
    expect(screen.queryByText(/^promoción aplicada$/i)).not.toBeInTheDocument();
  });

  it('shows the promotion-not-found message for rejected_promotion_not_found, not success', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: { submitted: false, status: 'rejected_promotion_not_found' },
    });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/promoción no encontrada/i)).toBeInTheDocument());
    expect(screen.queryByText(/^promoción aplicada$/i)).not.toBeInTheDocument();
  });

  it('shows the price-unresolved message for rejected_price_unresolved, not success', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: { submitted: false, status: 'rejected_price_unresolved' },
    });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/no se pudo resolver el precio/i)).toBeInTheDocument());
    expect(screen.queryByText(/^promoción aplicada$/i)).not.toBeInTheDocument();
  });

  it('shows the read-unavailable message for rejected_read_unavailable, not success', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: { submitted: false, status: 'rejected_read_unavailable' },
    });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/servicio de ml no disponible, reintentá/i)).toBeInTheDocument());
    expect(screen.queryByText(/^promoción aplicada$/i)).not.toBeInTheDocument();
  });

  it('shows the proxy-rejected message for rejected_by_proxy, not success', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: { submitted: false, status: 'rejected_by_proxy' },
    });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/rechazado por ml/i)).toBeInTheDocument());
    expect(screen.queryByText(/^promoción aplicada$/i)).not.toBeInTheDocument();
  });

  it('shows a "servicio no disponible" message on a 503 response', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockRejectedValue({ response: { status: 503 } });
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/servicio de ml no disponible, reintentá/i)).toBeInTheDocument());
  });

  it('shows a safe generic error (not a false success) on a bare network error with no response', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockRejectedValue(new Error('Network Error'));
    render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() => expect(screen.getByText(/error al aplicar la promoción/i)).toBeInTheDocument());
    expect(screen.queryByText(/^promoción aplicada$/i)).not.toBeInTheDocument();
  });

  it('sends only { promotion_id, promotion_type } for SMART (no offer_id/price from FE)', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    render(
      <PromoApplyControl
        mla="MLA1"
        promotion={{ promotion_id: 'P-SMART', promotion_type: 'SMART', name: 'Smart promo', price: 100 }}
      />,
    );

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA1', {
        promotion_id: 'P-SMART',
        promotion_type: 'SMART',
      }),
    );
  });

  it('sends only { promotion_id, promotion_type } for PRE_NEGOTIATED (no offer_id/price from FE)', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    render(
      <PromoApplyControl
        mla="MLA1"
        promotion={{ promotion_id: 'P-PN', promotion_type: 'PRE_NEGOTIATED', name: 'Pre-negotiated promo', price: 100 }}
      />,
    );

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA1', {
        promotion_id: 'P-PN',
        promotion_type: 'PRE_NEGOTIATED',
      }),
    );
  });

  it('sends only { promotion_id, promotion_type } for PRICE_MATCHING (no offer_id/price from FE)', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    render(
      <PromoApplyControl
        mla="MLA1"
        promotion={{ promotion_id: 'P-PM', promotion_type: 'PRICE_MATCHING', name: 'Price matching promo', price: 100 }}
      />,
    );

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA1', {
        promotion_id: 'P-PM',
        promotion_type: 'PRICE_MATCHING',
      }),
    );
  });

  describe('applied promo (status started) — Desaplicar', () => {
    function startedPromo(overrides = {}) {
      return dealPromo({ status: 'started', ...overrides });
    }

    it('shows "Desaplicar" (not "Aplicar") for an applied promo', () => {
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      expect(screen.getByRole('button', { name: /^desaplicar$/i })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^aplicar$/i })).not.toBeInTheDocument();
    });

    it('a candidate promo still shows "Aplicar"', () => {
      render(<PromoApplyControl mla="MLA1" promotion={dealPromo({ status: 'candidate' })} />);

      expect(screen.getByRole('button', { name: /^aplicar$/i })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^desaplicar$/i })).not.toBeInTheDocument();
    });

    it('a pending promo shows only "Desaplicar" (already enrolled, REQ-5)', () => {
      render(<PromoApplyControl mla="MLA1" promotion={dealPromo({ status: 'pending' })} />);

      expect(screen.getByRole('button', { name: /^desaplicar$/i })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^aplicar$/i })).not.toBeInTheDocument();
    });

    it('requires confirmation and calls deletePromocionItem for a pending promo (REQ-6)', async () => {
      const user = userEvent.setup();
      promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'submitted' } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo({ status: 'pending' })} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      expect(screen.getByText(/¿desaplicar esta promoción\?/i)).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));
      await waitFor(() => expect(promocionesAPI.deletePromocionItem).toHaveBeenCalledTimes(1));
      expect(promocionesAPI.deletePromocionItem).toHaveBeenCalledWith('MLA1', {
        promotion_id: 'P1',
        promotion_type: 'DEAL',
      });
    });

    it('requires confirmation and calls deletePromocionItem with the right params', async () => {
      const user = userEvent.setup();
      promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'submitted' } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      expect(promocionesAPI.deletePromocionItem).not.toHaveBeenCalled();
      expect(screen.getByText(/¿desaplicar esta promoción\?/i)).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));
      await waitFor(() => expect(promocionesAPI.deletePromocionItem).toHaveBeenCalledTimes(1));
      expect(promocionesAPI.deletePromocionItem).toHaveBeenCalledWith('MLA1', {
        promotion_id: 'P1',
        promotion_type: 'DEAL',
      });
      expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
    });

    it('cancelling the confirm step does not delete', async () => {
      const user = userEvent.setup();
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /cancelar/i }));

      expect(promocionesAPI.deletePromocionItem).not.toHaveBeenCalled();
      expect(screen.getByRole('button', { name: /^desaplicar$/i })).toBeInTheDocument();
    });

    it('disables the button while submitting', async () => {
      const user = userEvent.setup();
      let resolveDelete;
      promocionesAPI.deletePromocionItem.mockReturnValue(
        new Promise((resolve) => {
          resolveDelete = resolve;
        }),
      );
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

      expect(screen.getByRole('button', { name: /desaplicando/i })).toBeDisabled();

      resolveDelete({ data: { status: 'submitted' } });
      // The disabled submitting-phase button is gone once done; a distinct
      // (non-button) provisional indicator takes its place until the panel
      // reloads and confirms the new state — see the dedicated describe
      // block below for its contract.
      await waitFor(() =>
        expect(screen.queryByRole('button', { name: /desaplicando/i })).not.toBeInTheDocument(),
      );
      expect(screen.getByTestId('provisional-indicator')).toBeInTheDocument();
    });

    it('shows submitted feedback for a remove without claiming confirmed success', async () => {
      const user = userEvent.setup();
      promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'submitted' } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

      await waitFor(() => expect(screen.getByText(/puede tardar en reflejarse/i)).toBeInTheDocument());
    });

    it('shows ambiguous feedback for a remove', async () => {
      const user = userEvent.setup();
      promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'ambiguous' } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

      await waitFor(() => expect(screen.getByText(/estado por confirmar/i)).toBeInTheDocument());
    });

    it('shows reconciled_applied feedback for a remove', async () => {
      const user = userEvent.setup();
      promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'reconciled_applied' } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

      await waitFor(() => expect(screen.getByText(/promoción desaplicada/i)).toBeInTheDocument());
    });

    it('shows a rejected_* feedback for a remove', async () => {
      const user = userEvent.setup();
      promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'rejected_promotion_not_found' } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

      await waitFor(() => expect(screen.getByText(/promoción no encontrada/i)).toBeInTheDocument());
    });

    it('shows a kill-switch "disabled" message for a remove', async () => {
      const user = userEvent.setup();
      promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'disabled' } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

      await waitFor(() => expect(screen.getByText(/escritura deshabilitada/i)).toBeInTheDocument());
    });

    it('flips to "Desaplicar no disponible" on a 404 and does not auto-retry', async () => {
      const user = userEvent.setup();
      promocionesAPI.deletePromocionItem.mockRejectedValue({ response: { status: 404 } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

      await waitFor(() => expect(screen.getByText(/desaplicar no disponible/i)).toBeInTheDocument());
      expect(promocionesAPI.deletePromocionItem).toHaveBeenCalledTimes(1);
    });

    it('calls onApplied after a successful remove so the panel can refresh', async () => {
      const user = userEvent.setup();
      const onApplied = vi.fn();
      promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'reconciled_applied' } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo()} onApplied={onApplied} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

      await waitFor(() => expect(onApplied).toHaveBeenCalledWith({ status: 'reconciled_applied' }));
    });
  });

  describe('manual price input for range-based promos (SELLER_CAMPAIGN, DEAL)', () => {
    function rangePromo(overrides = {}) {
      return {
        promotion_id: 'P-SC',
        promotion_type: 'SELLER_CAMPAIGN',
        name: 'Seller campaign promo',
        price: 0,
        min_discounted_price: 700,
        max_discounted_price: 950,
        suggested_discounted_price: 900,
        ...overrides,
      };
    }

    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('shows a price input defaulting to suggested_discounted_price when confirming', async () => {
      const user = userEvent.setup({ delay: null });
      render(<PromoApplyControl mla="MLA1" promotion={rangePromo()} />);

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));

      const input = screen.getByLabelText(/precio/i);
      expect(input).toHaveValue(900);
    });

    it('fetches and shows the markup for the entered price (debounced)', async () => {
      const user = userEvent.setup({ delay: null });
      promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { price: 850, nuestro_markup: 22.5 } });
      render(<PromoApplyControl mla="MLA1" promotion={rangePromo()} />);

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
      const input = screen.getByLabelText(/precio/i);
      await user.clear(input);
      await user.type(input, '850');

      await vi.advanceTimersByTimeAsync(400);

      await waitFor(() => expect(promocionesAPI.getMarkupParaPrecio).toHaveBeenCalledWith('MLA1', 850));
      await waitFor(() => expect(screen.getByText(/22.5/)).toBeInTheDocument());
    });

    it('sends the entered deal_price on confirm', async () => {
      const user = userEvent.setup({ delay: null });
      promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { price: 800, nuestro_markup: 20 } });
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
      render(<PromoApplyControl mla="MLA1" promotion={rangePromo()} />);

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
      const input = screen.getByLabelText(/precio/i);
      await user.clear(input);
      await user.type(input, '800');
      await vi.advanceTimersByTimeAsync(400);
      await waitFor(() => expect(promocionesAPI.getMarkupParaPrecio).toHaveBeenCalled());

      await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

      await waitFor(() =>
        expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA1', {
          promotion_id: 'P-SC',
          promotion_type: 'SELLER_CAMPAIGN',
          deal_price: 800,
        }),
      );
    });

    it('blocks apply with an inline message when the price is out of range', async () => {
      const user = userEvent.setup({ delay: null });
      render(<PromoApplyControl mla="MLA1" promotion={rangePromo()} />);

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
      const input = screen.getByLabelText(/precio/i);
      await user.clear(input);
      await user.type(input, '1200');

      expect(screen.getByText(/fuera de rango/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /sí, aplicar/i })).toBeDisabled();
      expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
    });

    it('does NOT query the markup for an out-of-range price', async () => {
      const user = userEvent.setup({ delay: null });
      render(<PromoApplyControl mla="MLA1" promotion={rangePromo()} />);

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
      const input = screen.getByLabelText(/precio/i);
      await user.clear(input);
      await user.type(input, '1200'); // above max_discounted_price (950)

      await vi.advanceTimersByTimeAsync(400);

      expect(promocionesAPI.getMarkupParaPrecio).not.toHaveBeenCalled();
    });

    it('does NOT query the markup in the Desaplicar flow (started range promo)', async () => {
      const user = userEvent.setup({ delay: null });
      render(<PromoApplyControl mla="MLA1" promotion={rangePromo({ status: 'started' })} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await vi.advanceTimersByTimeAsync(400);

      expect(screen.queryByLabelText(/precio/i)).not.toBeInTheDocument();
      expect(promocionesAPI.getMarkupParaPrecio).not.toHaveBeenCalled();
    });

    it('does NOT show a price input for SMART (backend derives)', async () => {
      const user = userEvent.setup({ delay: null });
      render(
        <PromoApplyControl
          mla="MLA1"
          promotion={{ promotion_id: 'P-SM', promotion_type: 'SMART', name: 'Smart', price: 100 }}
        />,
      );

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
      expect(screen.queryByLabelText(/precio/i)).not.toBeInTheDocument();
    });

    it('does NOT show a price input for PRE_NEGOTIATED (backend derives)', async () => {
      const user = userEvent.setup({ delay: null });
      render(
        <PromoApplyControl
          mla="MLA1"
          promotion={{ promotion_id: 'P-PN', promotion_type: 'PRE_NEGOTIATED', name: 'Pre-negotiated', price: 100 }}
        />,
      );

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
      expect(screen.queryByLabelText(/precio/i)).not.toBeInTheDocument();
    });
  });

  describe('provisional "Aplicando…/Desaplicando…" indicator (eventual-consistency-safe)', () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it('shows a distinct provisional badge after a submitted apply is confirmed — not the "Aplicada" badge', async () => {
      const user = userEvent.setup();
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'submitted' } });
      render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

      await waitFor(() => expect(screen.getByTestId('provisional-indicator')).toBeInTheDocument());
      expect(screen.getByTestId('provisional-indicator')).toHaveTextContent(/aplicando/i);
      // The provisional indicator is NOT the confirmed "Aplicada" badge — that
      // one lives in MlaPromocionesPanel, driven only by application_status.
      expect(screen.queryByText(/^aplicada$/i)).not.toBeInTheDocument();
    });

    it('shows a distinct provisional badge after a submitted remove is confirmed', async () => {
      const user = userEvent.setup();
      const startedPromo = { ...dealPromo(), status: 'started' };
      promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'reconciled_applied' } });
      render(<PromoApplyControl mla="MLA1" promotion={startedPromo} />);

      await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

      await waitFor(() => expect(screen.getByTestId('provisional-indicator')).toBeInTheDocument());
      expect(screen.getByTestId('provisional-indicator')).toHaveTextContent(/desaplicando/i);
    });

    it('does NOT show the provisional indicator for a non-state-changing outcome (e.g. rejected)', async () => {
      const user = userEvent.setup();
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'rejected_out_of_range' } });
      render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

      await waitFor(() => expect(screen.getByText(/precio fuera de rango/i)).toBeInTheDocument());
      expect(screen.queryByTestId('provisional-indicator')).not.toBeInTheDocument();
    });

    it('clears the provisional indicator when reloaded props reflect the new confirmed state', async () => {
      const user = userEvent.setup();
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'submitted' } });
      const { rerender } = render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

      await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
      await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

      await waitFor(() => expect(screen.getByTestId('provisional-indicator')).toBeInTheDocument());

      // Panel reloaded and now passes a promotion prop reflecting the new
      // confirmed status — the provisional local indicator must clear.
      rerender(
        <PromoApplyControl
          mla="MLA1"
          promotion={{ ...dealPromo(), status: 'started', application_status: 'active' }}
        />,
      );

      await waitFor(() => expect(screen.queryByTestId('provisional-indicator')).not.toBeInTheDocument());
    });

    it('clears the provisional indicator via a ~90s safety timeout even if the table never reflects it', async () => {
      vi.useFakeTimers();
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'submitted' } });
      render(<PromoApplyControl mla="MLA1" promotion={dealPromo()} />);

      fireEventClick.click(screen.getByRole('button', { name: /^aplicar$/i }));
      fireEventClick.click(screen.getByRole('button', { name: /sí, aplicar/i }));

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(screen.getByTestId('provisional-indicator')).toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(89999);
      });
      expect(screen.getByTestId('provisional-indicator')).toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(2000);
      });
      expect(screen.queryByTestId('provisional-indicator')).not.toBeInTheDocument();
    });
  });
});
