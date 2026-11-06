import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromoApplyControl from './PromoApplyControl';
import { promocionesAPI } from '../../services/api';
import capture from './__fixtures__/lightning_item_promotions_20261106.json';

// LIGHTNING (ofertas relámpago), odd/tasks/promos-aplicar-lightning.md S1, S1b, S1c, S3, S4.
// Rows are the real ml_item_promotions capture of 2026-11-06 (same shape GET /promociones/item returns).

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

function row(mla, overrides = {}) {
  const found = capture.rows.find((r) => r.mla === mla && r.status === 'candidate');
  return { ...structuredClone(found), ...overrides };
}

async function openConfirm(user, promotion) {
  render(<PromoApplyControl mla={promotion.mla} promotion={promotion} />);
  await user.click(screen.getByRole('button', { name: /^aplicar$/i }));
}

describe('PromoApplyControl — LIGHTNING', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 12.3 } });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('offers Aplicar for a LIGHTNING candidate', () => {
    render(<PromoApplyControl mla="MLA4161234030" promotion={row('MLA4161234030')} />);

    expect(screen.getByRole('button', { name: /^aplicar$/i })).toBeInTheDocument();
    expect(screen.queryByText(/lo maneja ml/i)).not.toBeInTheDocument();
  });

  it('defaults the price to ML price when it is inside the range (MLA4161234030)', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA4161234030'));

    expect(screen.getByLabelText(/^precio/i)).toHaveValue(23280);
  });

  it('clamps the default to the max when ML price is above it (MLA3854324204: 14631.58 -> 14290.2)', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA3854324204'));

    expect(screen.getByLabelText(/^precio/i)).toHaveValue(14290.2);
  });

  it('clamps the default to the min when ML price is below it', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA4161234030', { price: 5000 }));

    expect(screen.getByLabelText(/^precio/i)).toHaveValue(5664.32);
  });

  it('keeps ML price as default when max is null but blocks the submit the backend would refuse (MLA1865080493)', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA1865080493'));

    expect(screen.getByLabelText(/^precio/i)).toHaveValue(23818.35);
    expect(
      screen.getByText('ML no informa el precio máximo de esta oferta relámpago; no se puede aplicar.'),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^stock a reservar/i), '6');
    expect(screen.getByRole('button', { name: /sí, aplicar/i })).toBeDisabled();
  });

  it('asks for the stock to reserve within ML range and keeps Aplicar disabled until it is valid', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA4161234030'));

    expect(screen.getByText(/entre 5 y 10 unidades/i)).toBeInTheDocument();
    const confirm = screen.getByRole('button', { name: /sí, aplicar/i });
    expect(confirm).toBeDisabled();

    const stock = screen.getByLabelText(/stock a reservar/i);
    await user.type(stock, '11');
    expect(confirm).toBeDisabled();

    await user.clear(stock);
    await user.type(stock, '6');
    expect(confirm).toBeEnabled();
  });

  it('posts deal_price and stock', async () => {
    const user = userEvent.setup({ delay: null });
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    await openConfirm(user, row('MLA4161234030'));

    await user.type(screen.getByLabelText(/stock a reservar/i), '6');
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA4161234030', {
        promotion_id: 'LGH-MLA1000',
        promotion_type: 'LIGHTNING',
        deal_price: 23280,
        stock: 6,
      }),
    );
  });

  it('warns that a started offer cannot be removed and ends when the stock sells out', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA4161234030'));

    expect(
      screen.getByText(
        'Una vez que empieza no se puede quitar (solo pausando la publicación). La oferta termina cuando se vende el stock reservado.',
      ),
    ).toBeInTheDocument();
  });

  it('updates the markup live while typing the price, reusing the debounced lookup (S1b)', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA4161234030'));

    const input = screen.getByLabelText(/^precio/i);
    await user.clear(input);
    await user.type(input, '22000');
    await vi.advanceTimersByTimeAsync(400);

    await waitFor(() => expect(promocionesAPI.getMarkupParaPrecio).toHaveBeenCalledWith('MLA4161234030', 22000));
    await waitFor(() => expect(screen.getByText(/tu markup: 12.3%/i)).toBeInTheDocument());
  });

  it('flags a typed price above the max and blocks the submit', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA3854324204'));

    await user.type(screen.getByLabelText(/stock a reservar/i), '6');
    const input = screen.getByLabelText(/^precio/i);
    await user.clear(input);
    await user.type(input, '14631.58');

    expect(screen.getByText(/precio fuera de rango/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sí, aplicar/i })).toBeDisabled();
  });

  it('blocks the submit when ML does not report the stock range', async () => {
    const user = userEvent.setup({ delay: null });
    const promotion = row('MLA4161234030');
    delete promotion.payload.stock;
    await openConfirm(user, promotion);

    expect(screen.getByText(/ml no informa el stock/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sí, aplicar/i })).toBeDisabled();
  });

  it('shows no dates nor boost line when the entry has none (captured shape)', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA4161234030'));

    expect(screen.queryByText(/^Empieza /)).not.toBeInTheDocument();
    expect(screen.queryByText(/descuento extra/i)).not.toBeInTheDocument();
  });

  it('shows the start/finish and the boosted buyer price only when ML brings them', async () => {
    const user = userEvent.setup({ delay: null });
    const promotion = row('MLA4161234030', {
      start_date: '2026-11-10T09:00:00-03:00',
      finish_date: '2026-11-10T15:00:00-03:00',
    });
    promotion.payload = {
      ...promotion.payload,
      boosted_offer: true,
      discount_meli_boosted_percentage: 5,
      total_price_for_boosted_offer: 22116,
    };
    await openConfirm(user, promotion);

    expect(screen.getByText(/empieza 10\/11 09:00 · termina 10\/11 15:00/i)).toBeInTheDocument();
    expect(screen.getByText(/ml suma 5% de descuento extra · el comprador paga \$22\.116/i)).toBeInTheDocument();
  });

  it('offers Desaplicar while pending', () => {
    render(<PromoApplyControl mla="MLA4161234030" promotion={row('MLA4161234030', { status: 'pending' })} />);

    expect(screen.getByRole('button', { name: /^desaplicar$/i })).toBeInTheDocument();
  });

  it('offers no remove once started and says why', () => {
    render(<PromoApplyControl mla="MLA4161234030" promotion={row('MLA4161234030', { status: 'started' })} />);

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(
      screen.getByText('ML no permite quitarla una vez iniciada; pausá la publicación para frenarla.'),
    ).toBeInTheDocument();
  });
});
