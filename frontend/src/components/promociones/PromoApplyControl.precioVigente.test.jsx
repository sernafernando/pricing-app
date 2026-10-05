// Incident 2026-10-05 (MLA2385168136, SMART): the panel showed a stale
// ~$469k offer, the operator applied it, and ML enrolled the item at its
// current $372.408,72 with negative markup. These tests pin the panel side
// of the guard: the price the operator SAW travels with the apply, a 409
// "price changed" asks again at the new price (never applies silently), and
// a post-apply price mismatch is shown in red with a one-click removal.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromoApplyControl from './PromoApplyControl';
import { promocionesAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    postPromocionItem: vi.fn(),
    deletePromocionItem: vi.fn(),
    getMarkupParaPrecio: vi.fn(),
  },
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const STALE = 469120;
const LIVE = 372408.72;

function smartPromo(overrides = {}) {
  return {
    promotion_id: 'P-MLA18091086',
    promotion_type: 'SMART',
    status: 'candidate',
    name: 'Ofertas compartidas 10.10',
    price: STALE,
    nuestro_markup: 12.5,
    ...overrides,
  };
}

function priceChanged409({ precioActual = LIVE, markupActual = -7.5 } = {}) {
  const err = new Error('Request failed with status code 409');
  // The app-wide exception handler puts a dict detail at the body root.
  err.response = {
    status: 409,
    data: {
      status: 'rejected_price_changed',
      mensaje: 'ML cambió el precio de la oferta desde que la viste. No se aplicó nada.',
      precio_visto: STALE,
      precio_actual: precioActual,
      markup_visto: 12.5,
      markup_actual: markupActual,
    },
  };
  return err;
}

async function clickApplyAndConfirm(user) {
  await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
  await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));
}

describe('PromoApplyControl — apply at the price the operator saw', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each(['SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING'])(
    'sends the seen price and markup for %s',
    async (promotionType) => {
      const user = userEvent.setup();
      promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted', precio_difiere: false } });
      render(<PromoApplyControl mla="MLA1" promotion={smartPromo({ promotion_type: promotionType })} />);

      await clickApplyAndConfirm(user);

      await waitFor(() =>
        expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA1', {
          promotion_id: 'P-MLA18091086',
          promotion_type: promotionType,
          precio_visto: STALE,
          markup_visto: 12.5,
        }),
      );
    },
  );

  it('the seen price is the one the panel shows: suggested when price is 0', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted', precio_difiere: false } });
    render(
      <PromoApplyControl mla="MLA1" promotion={smartPromo({ price: 0, suggested_discounted_price: 1000 })} />,
    );

    await clickApplyAndConfirm(user);

    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith(
        'MLA1',
        expect.objectContaining({ precio_visto: 1000 }),
      ),
    );
  });

  it('does not post at all when there is no price to confirm', async () => {
    const user = userEvent.setup();
    render(<PromoApplyControl mla="MLA1" promotion={smartPromo({ price: 0, suggested_discounted_price: null })} />);

    await user.click(screen.getByRole('button', { name: /^aplicar$/i }));

    expect(screen.getByText(/no hay un precio para confirmar/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /sí, aplicar/i })).not.toBeInTheDocument();
    expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
  });

  it('on a 409 shows the new price and markup and asks again — no silent apply', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockRejectedValueOnce(priceChanged409());
    render(<PromoApplyControl mla="MLA1" promotion={smartPromo()} />);

    await clickApplyAndConfirm(user);

    expect(await screen.findByText(/¿aplicar igual a \$372\.408,72 \(markup -7\.5%\)\?/i)).toBeInTheDocument();
    expect(screen.getByText(/\$469\.120/)).toBeInTheDocument();
    expect(promocionesAPI.postPromocionItem).toHaveBeenCalledTimes(1);
    // Negative markup reads red.
    expect(screen.getByTestId('markup-actual').className).toMatch(/markupNegative/);
  });

  it('confirming re-sends with the NEW seen price, still guarded', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem
      .mockRejectedValueOnce(priceChanged409())
      .mockResolvedValueOnce({ data: { submitted: true, status: 'submitted', precio_difiere: false } });
    render(<PromoApplyControl mla="MLA1" promotion={smartPromo()} />);

    await clickApplyAndConfirm(user);
    await user.click(await screen.findByRole('button', { name: /sí, aplicar a \$372\.408,72/i }));

    await waitFor(() => expect(promocionesAPI.postPromocionItem).toHaveBeenCalledTimes(2));
    expect(promocionesAPI.postPromocionItem).toHaveBeenLastCalledWith('MLA1', {
      promotion_id: 'P-MLA18091086',
      promotion_type: 'SMART',
      precio_visto: LIVE,
      markup_visto: -7.5,
    });
  });

  it('cancelling the re-ask sends nothing more', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockRejectedValueOnce(priceChanged409());
    render(<PromoApplyControl mla="MLA1" promotion={smartPromo()} />);

    await clickApplyAndConfirm(user);
    await screen.findByText(/¿aplicar igual a/i);
    await user.click(screen.getByRole('button', { name: /cancelar/i }));

    expect(promocionesAPI.postPromocionItem).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /^aplicar$/i })).toBeInTheDocument();
  });

  it('a 409 for an offer that is no longer a candidate shows its message', async () => {
    const user = userEvent.setup();
    const err = new Error('409');
    err.response = {
      status: 409,
      data: { error: { code: 'CONFLICT', message: 'La oferta ya no está disponible para aplicar en ML (estado actual: started).' } },
    };
    promocionesAPI.postPromocionItem.mockRejectedValueOnce(err);
    render(<PromoApplyControl mla="MLA1" promotion={smartPromo()} />);

    await clickApplyAndConfirm(user);

    expect(await screen.findByText(/ya no está disponible para aplicar en ml/i)).toBeInTheDocument();
  });

  it('DEAL keeps its contract: no seen-price fields', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    render(<PromoApplyControl mla="MLA1" promotion={{ promotion_id: 'D1', promotion_type: 'DEAL', price: 80 }} />);

    await clickApplyAndConfirm(user);

    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA1', { promotion_id: 'D1', promotion_type: 'DEAL' }),
    );
  });
});

describe('PromoApplyControl — post-apply price check', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('a different applied price shows a red alert with a one-click removal', async () => {
    const user = userEvent.setup();
    const onApplied = vi.fn();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: {
        submitted: true,
        status: 'submitted',
        precio_confirmado: LIVE,
        precio_aplicado: 350000,
        precio_difiere: true,
        markup_aplicado: -12.3,
      },
    });
    promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    render(<PromoApplyControl mla="MLA1" promotion={smartPromo({ price: LIVE })} onApplied={onApplied} />);

    await clickApplyAndConfirm(user);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/\$350\.000/);
    expect(alert.textContent).toMatch(/\$372\.408,72/);
    expect(alert.textContent).toMatch(/-12\.3%/);

    await user.click(screen.getByRole('button', { name: /quitar promo/i }));

    await waitFor(() =>
      expect(promocionesAPI.deletePromocionItem).toHaveBeenCalledWith('MLA1', {
        promotion_id: 'P-MLA18091086',
        promotion_type: 'SMART',
      }),
    );
    expect(onApplied).toHaveBeenCalledTimes(2);
  });

  it('an unverifiable applied price warns instead of passing as fine', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: { submitted: true, status: 'submitted', precio_confirmado: LIVE, precio_aplicado: null, precio_difiere: null },
    });
    render(<PromoApplyControl mla="MLA1" promotion={smartPromo({ price: LIVE })} />);

    await clickApplyAndConfirm(user);

    expect(await screen.findByText(/no se pudo verificar el precio aplicado/i)).toBeInTheDocument();
  });

  it('a verified equal price shows no alert', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockResolvedValue({
      data: { submitted: true, status: 'submitted', precio_confirmado: LIVE, precio_aplicado: LIVE, precio_difiere: false },
    });
    render(<PromoApplyControl mla="MLA1" promotion={smartPromo({ price: LIVE })} />);

    await clickApplyAndConfirm(user);

    await screen.findByText(/enviado/i);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/no se pudo verificar/i)).not.toBeInTheDocument();
  });
});
