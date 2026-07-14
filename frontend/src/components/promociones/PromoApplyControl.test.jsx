import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromoApplyControl from './PromoApplyControl';
import { promocionesAPI } from '../../services/api';

const mockTienePermiso = vi.fn(() => true);

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    postPromocionItem: vi.fn(),
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
});
