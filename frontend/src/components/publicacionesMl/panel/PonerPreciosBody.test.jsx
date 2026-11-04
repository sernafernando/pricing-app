import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PonerPreciosBody from './PonerPreciosBody';
import { preciosAPI, promocionesAPI } from '../../../services/api';
import capture from './fixtures/ponerPreciosPromos.capture.json';

vi.mock('../../../services/api', () => ({
  preciosAPI: { setRapido: vi.fn(), setCuota: vi.fn() },
  promocionesAPI: {
    getMarkupParaPrecio: vi.fn(),
    getPromocionesItem: vi.fn(),
    postPromocionItem: vi.fn(),
    descartarHayMejores: vi.fn(),
  },
}));

vi.mock('../../ModalTesla', () => ({
  default: ({ isOpen, title, children, footer }) =>
    isOpen ? (
      <div role="dialog" aria-label={title}>
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
});

describe('PonerPreciosBody flagged hay_mejores', () => {
  const flaggedDetail = {
    ...detail,
    row: { ...detail.row, hay_mejores_ofertas: true, price: { amount: 80000, pricelist_id: 4, lista_nombre: 'Clásica' } },
  };

  beforeEach(() => {
    // Baseline markup 10% so SMART (20) / DEAL (12) / Premium (15) at lower offer prices all qualify.
    promocionesAPI.getMarkupParaPrecio.mockResolvedValue({ data: { nuestro_markup: 10 } });
  });

  it('hides Nuevo precio until Descartar, then shows it', async () => {
    const user = userEvent.setup();
    render(<PonerPreciosBody detail={flaggedDetail} itemId="MLA1" canEditPrice canWritePromos />);
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
    await screen.findByRole('region', { name: 'Candidatas mejores' });
    await screen.findByRole('button', { name: /SMART/i });
    await user.click(screen.getByRole('button', { name: 'Descartar sugerencia' }));
    await waitFor(() => expect(promocionesAPI.descartarHayMejores).toHaveBeenCalledWith('MLA1'));
    expect(await screen.findByLabelText('Nuevo precio')).toBeInTheDocument();
  });

  it('applies a mejores SMART and leaves the pub without showing Nuevo precio', async () => {
    const user = userEvent.setup();
    const onLeavePub = vi.fn();
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
    await user.click(await screen.findByRole('button', { name: /SMART/i }));
    await waitFor(() =>
      expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith(
        'MLA1',
        expect.objectContaining({ promotion_id: 'P-MLA18137008', promotion_type: 'SMART' }),
      ),
    );
    expect(onLeavePub).toHaveBeenCalled();
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
  });
});
