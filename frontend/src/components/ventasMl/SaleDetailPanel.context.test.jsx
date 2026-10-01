/**
 * ODD `ventas-ml-ui-pendiente` T4: the Comprador / Pago / Envio sections and
 * the header identity row (copy id + "Ver en ML") of SaleDetailPanel. Data
 * comes from the SAME `GET /ml-ventas-ops/orders/{id}` response.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SaleDetailPanel from './SaleDetailPanel';
import api from '../../services/api';

const BREAKDOWN = { lines: [], neto: 1, incompleto: false, incomplete_reasons: [], item_lines: [] };

const DETAIL = {
  breakdown: BREAKDOWN,
  order: {
    order_id: 2000018567320906,
    pack_id: null,
    buyer_nickname: 'JUAN_PEREZ_92',
    buyer_first_name: 'Juan Carlos',
    buyer_last_name: 'Pérez',
    payment_method_id: 'master',
    installments: 6,
    paid_amount: 555729,
    coupon_amount: 41679.67,
    payment_date_approved: '2026-09-21T12:13:00.000Z',
  },
  shipment: {
    shipment_id: 1,
    status: 'shipped',
    substatus: 'out_for_delivery',
    tracking_number: 'MEL-849201948',
    modo_logistico: 'cross_docking',
    city: 'Palermo',
    province: 'Capital Federal',
    estimated_delivery: '2026-09-22T12:00:00.000Z',
  },
};

function mockDetail(detail) {
  api.get.mockImplementation((url) =>
    Promise.resolve({ data: url.startsWith('/ml-ventas-ops/orders/') ? detail : {} }),
  );
}

beforeEach(() => {
  api.get.mockReset();
});

describe('Comprador / Pago / Envio sections', () => {
  it('shows the buyer, where it ships to, how it was paid and how it ships', async () => {
    mockDetail(DETAIL);
    render(<SaleDetailPanel orderId={2000018567320906} onClose={vi.fn()} />);

    const comprador = await screen.findByRole('region', { name: 'Comprador' });
    expect(within(comprador).getByText('JUAN_PEREZ_92')).toBeInTheDocument();
    expect(within(comprador).getByText('Juan Carlos Pérez')).toBeInTheDocument();
    expect(within(comprador).getByText('Palermo, Capital Federal')).toBeInTheDocument();

    const pago = screen.getByRole('region', { name: 'Pago' });
    expect(within(pago).getByText(/Mastercard/)).toBeInTheDocument();
    expect(within(pago).getByText(/6 cuotas/)).toBeInTheDocument();
    expect(within(pago).getByText('21/09/2026')).toBeInTheDocument();
    expect(within(pago).getByText('$ 555.729,00')).toBeInTheDocument();
    expect(within(pago).getByText('$ 41.679,67')).toBeInTheDocument();

    const envio = screen.getByRole('region', { name: 'Envío' });
    expect(within(envio).getByText('Colecta')).toBeInTheDocument();
    expect(within(envio).getByText('out_for_delivery')).toBeInTheDocument();
    expect(within(envio).getByText('MEL-849201948')).toBeInTheDocument();
    expect(within(envio).getByText('22/09/2026')).toBeInTheDocument();
  });

  it('hides a field it does not have instead of printing a blank or a zero', async () => {
    mockDetail({
      breakdown: BREAKDOWN,
      order: { order_id: 5, buyer_nickname: 'solo_nick', coupon_amount: 0, installments: 1 },
      shipment: null,
    });
    render(<SaleDetailPanel orderId={5} onClose={vi.fn()} />);

    const pago = await screen.findByRole('region', { name: 'Pago' });
    expect(within(pago).queryByText(/Cupón/)).not.toBeInTheDocument();
    expect(within(pago).queryByText(/Aprobación/)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Envío' })).not.toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Comprador' })).queryByText(/,/)).not.toBeInTheDocument();
  });

  it('renders no new sections for a response without `order` (old-shaped payload)', async () => {
    mockDetail({ breakdown: BREAKDOWN });
    render(<SaleDetailPanel orderId={7} onClose={vi.fn()} />);
    expect(await screen.findByText('Desglose de costos')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Comprador' })).not.toBeInTheDocument();
  });
});

describe('header identity row', () => {
  it('links to the sale on Mercado Libre in a new tab', async () => {
    mockDetail(DETAIL);
    render(<SaleDetailPanel orderId={2000018567320906} onClose={vi.fn()} />);
    const link = await screen.findByRole('link', { name: /Ver en ML/ });
    expect(link).toHaveAttribute('href', 'https://www.mercadolibre.com.ar/ventas/2000018567320906/detalle');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('links by pack id when the order is part of a pack', async () => {
    mockDetail({ ...DETAIL, order: { ...DETAIL.order, pack_id: 2000099900000001 } });
    render(<SaleDetailPanel orderId={2000018567320906} onClose={vi.fn()} />);
    expect(await screen.findByRole('link', { name: /Ver en ML/ })).toHaveAttribute(
      'href',
      'https://www.mercadolibre.com.ar/ventas/2000099900000001/detalle',
    );
  });

  it('copies the order id and the tracking number', async () => {
    const user = userEvent.setup();
    // After `setup()`: user-event installs its own clipboard stub there.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    mockDetail(DETAIL);
    render(<SaleDetailPanel orderId={2000018567320906} onClose={vi.fn()} />);

    await user.click(await screen.findByRole('button', { name: 'Copiar ID de la orden' }));
    expect(writeText).toHaveBeenCalledWith('2000018567320906');
    expect(await screen.findByText('Copiado')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Copiar número de seguimiento' }));
    expect(writeText).toHaveBeenCalledWith('MEL-849201948');
  });

  it('does not crash when the clipboard is unavailable', async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    mockDetail(DETAIL);
    render(<SaleDetailPanel orderId={2000018567320906} onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Copiar ID de la orden' }));
    expect(screen.getByRole('button', { name: 'Copiar ID de la orden' })).toBeInTheDocument();
  });
});
