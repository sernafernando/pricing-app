import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PonerPreciosBody from './PonerPreciosBody';
import { preciosAPI, promocionesAPI } from '../../../services/api';
import capture from './fixtures/ponerPreciosPromos.capture.json';
// Real LIGHTNING rows (owner capture 2026-11-06), shared with PromoApplyControl.lightning.test.jsx.
import lightningCapture from '../../promociones/fixtures/lightning_item_promotions_20261106.json';

vi.mock('../../../services/api', () => ({
  preciosAPI: { setRapido: vi.fn(), setCuota: vi.fn() },
  promocionesAPI: {
    getMarkupParaPrecio: vi.fn(),
    getPromocionesItem: vi.fn(),
    postPromocionItem: vi.fn(),
    descartarHayMejores: vi.fn(),
  },
}));

vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../ModalTesla', () => ({
  default: ({ isOpen, title, subtitle, children, footer }) =>
    isOpen ? (
      <div role="dialog" aria-label={title}>
        {subtitle && <p data-testid="modal-subtitle">{subtitle}</p>}
        {children}
        {footer}
      </div>
    ) : null,
  ModalFooterButtons: ({ onCancel, cancelText }) => (
    <button type="button" onClick={onCancel}>
      {cancelText || 'Cancelar'}
    </button>
  ),
}));

/** Map a captured seller-promotions entry to the enriched shape GET /promociones/item returns. */
function asApiPromo(raw, nuestro_markup) {
  return {
    promotion_id: raw.id,
    promotion_type: raw.type,
    status: raw.status,
    name: raw.name,
    price: raw.price,
    original_price: raw.original_price,
    suggested_discounted_price: raw.suggested_discounted_price,
    min_discounted_price: raw.min_discounted_price,
    max_discounted_price: raw.max_discounted_price,
    meli_percentage: raw.meli_percentage,
    seller_percentage: raw.seller_percentage,
    nuestro_markup,
  };
}

const markups = { SMART: 20, DEAL: 12, SELLER_CAMPAIGN: 15 };
const capturedPromotions = capture.promotions.map((raw) => asApiPromo(raw, markups[raw.type]));

const detail = {
  row: {
    price: { amount: 1500, pricelist_id: 4, lista_nombre: 'Clásica' },
    link: { codigo: 'SKU-1', producto_item_id: 4101 },
  },
  product: { item_id: 4101, recalcular_cuotas_auto: false },
};

beforeEach(() => {
  preciosAPI.setRapido.mockReset().mockResolvedValue({ data: {} });
  promocionesAPI.getMarkupParaPrecio.mockReset().mockResolvedValue({ data: { nuestro_markup: 18 } });
  promocionesAPI.getPromocionesItem.mockReset().mockResolvedValue({ data: { promotions: capturedPromotions } });
  promocionesAPI.postPromocionItem.mockReset().mockResolvedValue({ data: { status: 'submitted' } });
  promocionesAPI.descartarHayMejores.mockReset().mockResolvedValue({ data: { ok: true } });
});

describe('PonerPreciosBody Enter suggest', () => {
  it('writes Pricing, lets the PM pick one promo, then leaves the pub', async () => {
    const user = userEvent.setup();
    const onLeavePub = vi.fn();
    render(
      <PonerPreciosBody detail={detail} itemId="MLA1" canEditPrice canWritePromos onLeavePub={onLeavePub} />,
    );
    await user.clear(screen.getByLabelText('Nuevo precio'));
    await user.type(screen.getByLabelText('Nuevo precio'), '1600{Enter}');
    await screen.findByRole('dialog', { name: 'Elegí una promoción' });
    expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 4101, precio: 1600, recalcular_cuotas: false });
    await user.click(screen.getByRole('button', { name: /SMART/i }));
    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith(
        'MLA1',
        expect.objectContaining({ promotion_id: 'P-MLA18137008', promotion_type: 'SMART' }),
      ),
    );
    expect(onLeavePub).toHaveBeenCalled();
  });

  it('keeps the modal and always says Pricing was saved when enroll fails with a string detail', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockRejectedValueOnce({
      response: { data: { detail: 'Promoción no disponible' } },
    });
    render(<PonerPreciosBody detail={detail} itemId="MLA1" canEditPrice canWritePromos />);
    await user.clear(screen.getByLabelText('Nuevo precio'));
    await user.type(screen.getByLabelText('Nuevo precio'), '1600{Enter}');
    await screen.findByRole('dialog', { name: 'Elegí una promoción' });
    await user.click(screen.getByRole('button', { name: /SMART/i }));
    expect(await screen.findByRole('status')).toHaveTextContent(
      /El precio ya está guardado en Pricing\. Promoción no disponible/,
    );
    expect(screen.getByRole('dialog', { name: 'Elegí una promoción' })).toBeInTheDocument();
  });

  it('uses the generic fallback after Pricing-saved when enroll fails without a string detail', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockRejectedValueOnce(new Error('network'));
    render(<PonerPreciosBody detail={detail} itemId="MLA1" canEditPrice canWritePromos />);
    await user.clear(screen.getByLabelText('Nuevo precio'));
    await user.type(screen.getByLabelText('Nuevo precio'), '1600{Enter}');
    await screen.findByRole('dialog', { name: 'Elegí una promoción' });
    await user.click(screen.getByRole('button', { name: /SMART/i }));
    expect(await screen.findByRole('status')).toHaveTextContent(
      /El precio ya está guardado en Pricing\. No se pudo activar la promoción\./,
    );
  });

  it('says Pricing was saved when loading candidatas fails after a successful price write', async () => {
    const user = userEvent.setup();
    promocionesAPI.getPromocionesItem.mockRejectedValueOnce(new Error('boom'));
    render(<PonerPreciosBody detail={detail} itemId="MLA1" canEditPrice canWritePromos />);
    await user.clear(screen.getByLabelText('Nuevo precio'));
    await user.type(screen.getByLabelText('Nuevo precio'), '1600{Enter}');
    expect(await screen.findByRole('status')).toHaveTextContent(
      /Precio guardado en Pricing\. No se pudieron cargar las candidatas/,
    );
    expect(preciosAPI.setRapido).toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: 'Elegí una promoción' })).not.toBeInTheDocument();
  });
});

// promos-markup-sell-in-out S2: the markup with sell in / sell out next to each markup of the chooser.
describe('PonerPreciosBody sell in / sell out markup', () => {
  async function openChooser() {
    const user = userEvent.setup();
    render(<PonerPreciosBody detail={detail} itemId="MLA1" canEditPrice canWritePromos />);
    await user.clear(screen.getByLabelText('Nuevo precio'));
    await user.type(screen.getByLabelText('Nuevo precio'), '1600{Enter}');
    return screen.findByRole('dialog', { name: 'Elegí una promoción' });
  }

  it('shows it next to the typed price markup and each proposed promo markup when the backend sends it', async () => {
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 18, markup_sell_in_out: 22.5 } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: capturedPromotions.map((p) => ({ ...p, markup_sell_in_out: p.nuestro_markup + 4 })) },
    });

    await openChooser();

    expect(screen.getByTestId('modal-subtitle').textContent).toBe(
      'Precio en Pricing: $ 1.600,00 · markup 18,00% · c/ sell in/out 22,50%',
    );
    expect(screen.getByRole('button', { name: /SMART/i }).textContent).toContain(
      ' · markup 20,00% · c/ sell in/out 24,00%',
    );
  });

  it('shows no sell in / sell out figure when the backend sends null', async () => {
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 18, markup_sell_in_out: null } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: capturedPromotions.map((p) => ({ ...p, markup_sell_in_out: null })) },
    });

    const dialog = await openChooser();

    expect(screen.getByTestId('modal-subtitle').textContent).toBe('Precio en Pricing: $ 1.600,00 · markup 18,00%');
    expect(dialog.textContent).not.toContain('sell in/out');
  });
});

describe('PonerPreciosBody flagged hay_mejores', () => {
  const flaggedDetail = {
    ...detail,
    row: { ...detail.row, hay_mejores_ofertas: true, price: { amount: 80000, pricelist_id: 4, lista_nombre: 'Clásica' } },
  };

  beforeEach(() => {
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 10 } });
  });

  it('hides Nuevo precio until Descartar, then shows it', async () => {
    const user = userEvent.setup();
    render(<PonerPreciosBody detail={flaggedDetail} itemId="MLA1" canEditPrice canWritePromos />);
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
    await screen.findByRole('region', { name: 'Candidatas mejores' });
    await screen.findByRole('button', { name: 'Aplicar sugerencia' });
    await user.click(screen.getByRole('button', { name: 'Descartar sugerencia' }));
    await waitFor(() => expect(promocionesAPI.descartarHayMejores).toHaveBeenCalledWith('MLA1'));
    expect(await screen.findByLabelText('Nuevo precio')).toBeInTheDocument();
  });

  it('applies a mejores SMART after confirming and leaves the pub without showing Nuevo precio', async () => {
    const user = userEvent.setup();
    const onLeavePub = vi.fn();
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { status: 'submitted', precio_difiere: false } });
    render(
      <PonerPreciosBody
        detail={flaggedDetail}
        itemId="MLA1"
        canEditPrice
        canWritePromos
        onLeavePub={onLeavePub}
      />,
    );
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
    expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith('MLA1', {
        promotion_id: 'P-MLA18137008',
        promotion_type: 'SMART',
        precio_visto: 74690,
        markup_visto: 20,
      }),
    );
    expect(onLeavePub).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
  });

  it('stays on the pub when ML moved the price (409)', async () => {
    const user = userEvent.setup();
    const onLeavePub = vi.fn();
    promocionesAPI.postPromocionItem.mockRejectedValueOnce({
      response: { status: 409, data: { status: 'rejected_price_changed', precio_actual: 75000, markup_actual: 19 } },
    });
    render(<PonerPreciosBody detail={flaggedDetail} itemId="MLA1" canEditPrice canWritePromos onLeavePub={onLeavePub} />);
    await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
    await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
    expect(await screen.findByText(/ML cambió el precio/)).toBeInTheDocument();
    expect(onLeavePub).not.toHaveBeenCalled();
    expect(screen.getByRole('region', { name: 'Candidatas mejores' })).toBeInTheDocument();
  });

  it('shows Nuevo precio immediately without promos.escribir', () => {
    render(<PonerPreciosBody detail={flaggedDetail} itemId="MLA1" canEditPrice canWritePromos={false} />);
    expect(screen.getByLabelText('Nuevo precio')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Candidatas mejores' })).not.toBeInTheDocument();
  });

  it('keeps Descartar when baseline markup cannot be computed, then unlocks Nuevo precio', async () => {
    const user = userEvent.setup();
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: null } });
    render(<PonerPreciosBody detail={flaggedDetail} itemId="MLA1" canEditPrice canWritePromos />);
    const region = await screen.findByRole('region', { name: 'Candidatas mejores' });
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
    await user.click(within(region).getByRole('button', { name: 'Descartar sugerencia' }));
    expect(await screen.findByLabelText('Nuevo precio')).toBeInTheDocument();
  });

  it('keeps the load error visible in MODO until Descartar (does not unlock Nuevo precio alone)', async () => {
    const user = userEvent.setup();
    promocionesAPI.getPromocionesItem.mockRejectedValue(new Error('boom'));
    render(<PonerPreciosBody detail={flaggedDetail} itemId="MLA1" canEditPrice canWritePromos />);
    const region = await screen.findByRole('region', { name: 'Candidatas mejores' });
    expect(within(region).getByText(/No se pudieron cargar las candidatas/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
    await user.click(within(region).getByRole('button', { name: 'Descartar sugerencia' }));
    expect(await screen.findByLabelText('Nuevo precio')).toBeInTheDocument();
  });

  it('keeps the chooser and shows an error when apply fails', async () => {
    const user = userEvent.setup();
    const onLeavePub = vi.fn();
    promocionesAPI.postPromocionItem.mockRejectedValueOnce({
      response: { status: 422, data: { detail: 'Promoción no disponible' } },
    });
    render(<PonerPreciosBody detail={flaggedDetail} itemId="MLA1" canEditPrice canWritePromos onLeavePub={onLeavePub} />);
    await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
    await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
    expect(await screen.findByText('Promoción no disponible')).toBeInTheDocument();
    expect(onLeavePub).not.toHaveBeenCalled();
    expect(screen.getByRole('region', { name: 'Candidatas mejores' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
  });

  it('keeps the chooser and shows an error when discard fails', async () => {
    const user = userEvent.setup();
    promocionesAPI.descartarHayMejores.mockRejectedValueOnce({
      response: { data: { detail: 'Sin permiso' } },
    });
    render(<PonerPreciosBody detail={flaggedDetail} itemId="MLA1" canEditPrice canWritePromos />);
    await user.click(await screen.findByRole('button', { name: 'Descartar sugerencia' }));
    expect(await screen.findByRole('status')).toHaveTextContent(/Sin permiso/);
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
  });
});

// hay-mejores-chooser-slots (#2142): one button per writable MeLi type, each with its own markup.
describe('PonerPreciosBody MeLi-type slots', () => {
  const lightning = {
    ...lightningCapture.rows.find((row) => row.mla === 'MLA1506729443' && row.status === 'candidate'),
    nuestro_markup: 21,
    markup_sell_in_out: 25.5,
  };

  async function openChooser(promotions) {
    const user = userEvent.setup();
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions } });
    render(<PonerPreciosBody detail={detail} itemId="MLA1506729443" canEditPrice canWritePromos />);
    await user.clear(screen.getByLabelText('Nuevo precio'));
    await user.type(screen.getByLabelText('Nuevo precio'), '1600{Enter}');
    await screen.findByRole('dialog', { name: 'Elegí una promoción' });
    return user;
  }

  it('shows c/ sell in/out on the LIGHTNING button like the other candidates', async () => {
    await openChooser([...capturedPromotions, lightning]);
    expect(screen.getByRole('button', { name: /LIGHTNING/ }).textContent).toContain(
      ' · markup 21,00% · c/ sell in/out 25,50%',
    );
  });

  it('asks for confirmation before applying LIGHTNING and reserves ML\'s minimum stock', async () => {
    const user = await openChooser([lightning]);
    await user.click(screen.getByRole('button', { name: /LIGHTNING/ }));
    expect(screen.getByText(/Una vez que empieza no se puede quitar/)).toBeInTheDocument();
    expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Sí, aplicar LIGHTNING' }));
    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith(
        'MLA1506729443',
        expect.objectContaining({ promotion_id: 'LGH-MLA1000', promotion_type: 'LIGHTNING', stock: 5 }),
      ),
    );
  });
});
