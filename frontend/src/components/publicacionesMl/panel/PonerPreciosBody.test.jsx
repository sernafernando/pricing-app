import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PonerPreciosBody from './PonerPreciosBody';
import { preciosAPI, promocionesAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  preciosAPI: { setRapido: vi.fn(), setCuota: vi.fn() },
  promocionesAPI: {
    getMarkupParaPrecio: vi.fn(),
    getPromocionesItem: vi.fn(),
    postPromocionItem: vi.fn(),
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
  promocionesAPI.getPromocionesItem.mockReset().mockResolvedValue({
    data: {
      promotions: [
        { promotion_id: 'smart-1', promotion_type: 'SMART', status: 'candidate', price: 1400, nuestro_markup: 20, name: 'Smart A' },
        {
          promotion_id: 'deal-1',
          promotion_type: 'DEAL',
          status: 'candidate',
          suggested_discounted_price: 1300,
          min_discounted_price: 1200,
          max_discounted_price: 1400,
          nuestro_markup: 12,
          name: 'Deal A',
        },
      ],
    },
  });
  promocionesAPI.postPromocionItem.mockReset().mockResolvedValue({ data: { status: 'submitted' } });
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
        expect.objectContaining({ promotion_id: 'smart-1', promotion_type: 'SMART' }),
      ),
    );
    expect(onLeavePub).toHaveBeenCalled();
  });

  it('keeps the modal and says Pricing already saved when enroll fails', async () => {
    const user = userEvent.setup();
    promocionesAPI.postPromocionItem.mockRejectedValueOnce(new Error('network'));
    render(<PonerPreciosBody detail={detail} itemId="MLA1" canEditPrice canWritePromos />);
    await user.clear(screen.getByLabelText('Nuevo precio'));
    await user.type(screen.getByLabelText('Nuevo precio'), '1600{Enter}');
    await screen.findByRole('dialog', { name: 'Elegí una promoción' });
    await user.click(screen.getByRole('button', { name: /SMART/i }));
    expect(await screen.findByRole('status')).toHaveTextContent(
      /precio ya está guardado en Pricing.*no se pudo activar/i,
    );
    expect(screen.getByRole('dialog', { name: 'Elegí una promoción' })).toBeInTheDocument();
  });
});
