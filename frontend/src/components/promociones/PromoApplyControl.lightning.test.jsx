import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromoApplyControl from './PromoApplyControl';
import { promocionesAPI } from '../../services/api';
// Copy of backend/tests/fixtures/ml_promotions/lightning_item_promotions_20261106.json (run_tests.sh frontend syncs only frontend/).
import capture from './fixtures/lightning_item_promotions_20261106.json';

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

  // `price` is not the lightning suggestion (MLA1506729443 price 57920.55 is the SMART candidate's):
  // the default is `suggested_discounted_price`, clamped to [min, max] only as a guard.
  it.each([
    ['MLA4161234030', 24073.36],
    ['MLA3854324204', 13496.3],
    ['MLA1506729443', 73558.15],
  ])('defaults the price to ML suggested_discounted_price (%s -> %s)', async (mla, expected) => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row(mla));

    expect(screen.getByLabelText(/^precio/i)).toHaveValue(expected);
  });

  it('clamps a suggested price above the max to the max (guard)', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA4161234030', { suggested_discounted_price: 30000 }));

    expect(screen.getByLabelText(/^precio/i)).toHaveValue(25489.44);
  });

  it('clamps a suggested price below the min to the min (guard)', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA4161234030', { suggested_discounted_price: 5000 }));

    expect(screen.getByLabelText(/^precio/i)).toHaveValue(5664.32);
  });

  it('leaves the max to the live read when the stored row has none (MLA1865080493)', async () => {
    const user = userEvent.setup({ delay: null });
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    await openConfirm(user, row('MLA1865080493'));

    // No suggested_discounted_price in this row: ML's price is the only reference.
    expect(screen.getByLabelText(/^precio/i)).toHaveValue(23818.35);
    expect(
      screen.getByText('ML no informó el precio máximo; se confirma con ML al aplicar.'),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^stock a reservar/i), '6');
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));

    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA1865080493', {
        promotion_id: 'LGH-MLA1000',
        promotion_type: 'LIGHTNING',
        deal_price: 23818.35,
        stock: 6,
      }),
    );
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
        deal_price: 24073.36,
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
    await waitFor(() => expect(screen.getByRole('status', { name: /tu markup/i })).toHaveTextContent('12.3%'));
  });

  it('shows the markup of the prefilled price on open, before any typing (S1b)', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA1506729443'));
    await vi.advanceTimersByTimeAsync(400);

    await waitFor(() => expect(promocionesAPI.getMarkupParaPrecio).toHaveBeenCalledWith('MLA1506729443', 73558.15));
    await waitFor(() => expect(screen.getByRole('status', { name: /tu markup/i })).toHaveTextContent('12.3%'));
  });

  // promos-markup-sell-in-out S2: the card shows the markup with sell in / sell out under its markup.
  it('shows the markup with sell in / sell out in the card when the backend sends it', async () => {
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 12.3, markup_sell_in_out: 16.04 } });
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA1506729443'));
    await vi.advanceTimersByTimeAsync(400);

    const card = screen.getByRole('group', { name: 'Aplicar LIGHTNING' });
    await waitFor(() => expect(card).toHaveTextContent('c/ sell in/out 16.0%'));
  });

  it('shows no sell in / sell out figure in the card when the backend sends null', async () => {
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 12.3, markup_sell_in_out: null } });
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA1506729443'));
    await vi.advanceTimersByTimeAsync(400);

    await waitFor(() => expect(screen.getByRole('status', { name: /tu markup/i })).toHaveTextContent('12.3%'));
    expect(screen.getByRole('group', { name: 'Aplicar LIGHTNING' })).not.toHaveTextContent('sell in/out');
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

  it('removes a pending offer with Desaplicar, sending only id and type (no price nor stock)', async () => {
    const user = userEvent.setup({ delay: null });
    promocionesAPI.deletePromocionItem.mockResolvedValue({ data: { status: 'submitted' } });
    render(<PromoApplyControl mla="MLA4161234030" promotion={row('MLA4161234030', { status: 'pending' })} />);

    await user.click(screen.getByRole('button', { name: /^desaplicar$/i }));
    expect(screen.queryByLabelText(/^stock a reservar/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /sí, desaplicar/i }));

    await waitFor(() => expect(promocionesAPI.deletePromocionItem).toHaveBeenCalledTimes(1));
    expect(promocionesAPI.deletePromocionItem).toHaveBeenCalledWith('MLA4161234030', {
      promotion_id: 'LGH-MLA1000',
      promotion_type: 'LIGHTNING',
    });
  });

  // Card of the approved design (docs/design/promos-panel-s9/propuesta.png).
  it('opens the form as an "Aplicar LIGHTNING" card and the trigger reads Cerrar, which closes it', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA1506729443'));

    expect(screen.getByRole('group', { name: 'Aplicar LIGHTNING' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^aplicar$/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^cerrar$/i }));

    expect(screen.queryByRole('group', { name: 'Aplicar LIGHTNING' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^stock a reservar/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^aplicar$/i })).toBeInTheDocument();
  });

  it('shows the allowed range under the price', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA1506729443'));

    expect(screen.getByText('Rango permitido: $17.307,81 - $77.885,10')).toBeInTheDocument();
  });

  it('shows only the minimum when ML sends no max', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA1865080493'));

    expect(screen.getByText('Mínimo permitido: $7.366,50')).toBeInTheDocument();
  });

  it('shows "—" as the markup until it is known', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA1506729443', { suggested_discounted_price: 90000, max_discounted_price: 77885.1 }));
    const input = screen.getByLabelText(/^precio/i);
    await user.clear(input);
    await user.type(input, '1');
    await vi.advanceTimersByTimeAsync(400);

    await waitFor(() => expect(screen.getByRole('status', { name: /tu markup/i })).toHaveTextContent('—'));
  });

  it('draws the cannot-remove warning as a note callout', async () => {
    const user = userEvent.setup({ delay: null });
    await openConfirm(user, row('MLA4161234030'));

    expect(screen.getByRole('note')).toHaveTextContent(
      'Una vez que empieza no se puede quitar (solo pausando la publicación). La oferta termina cuando se vende el stock reservado.',
    );
  });

  it('offers no remove once started and says why', () => {
    render(<PromoApplyControl mla="MLA4161234030" promotion={row('MLA4161234030', { status: 'started' })} />);

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(
      screen.getByText('ML no permite quitarla una vez iniciada; pausá la publicación para frenarla.'),
    ).toBeInTheDocument();
  });
});
