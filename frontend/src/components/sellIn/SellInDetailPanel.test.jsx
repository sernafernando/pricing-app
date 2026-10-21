import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { sellInAPI } from '../../services/sellInAPI';
import { COMPRA_ARS, COMPRA_BONO, COMPRA_CON_OPERACIONES, COMPRA_USD_ANULADA } from './sellInFixtures';
import SellInDetailPanel from './SellInDetailPanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { detalle: vi.fn(), anular: vi.fn() },
}));

const ANULADA = { ...COMPRA_ARS, estado: 'anulada', aplica: false };
const OTRA = { ...COMPRA_ARS, id: 3, descripcion: 'Otra compra' };
const porId = (id) => Promise.resolve({ data: id === 3 ? OTRA : COMPRA_ARS });

beforeEach(() => {
  vi.clearAllMocks();
  sellInAPI.detalle.mockResolvedValue({ data: COMPRA_ARS });
  sellInAPI.anular.mockResolvedValue({ data: ANULADA });
});

const renderPanel = (props = {}) => {
  const onChanged = vi.fn();
  const view = render(<SellInDetailPanel compraId={1} puedeGestionar onChanged={onChanged} onClose={vi.fn()} {...props} />);
  const cambiarA = (compraId) =>
    view.rerender(<SellInDetailPanel compraId={compraId} puedeGestionar onChanged={onChanged} onClose={vi.fn()} {...props} />);
  return { onChanged, cambiarA };
};

describe('SellInDetailPanel', () => {
  it('loads the purchase and shows its data and lines', async () => {
    renderPanel();
    expect(await screen.findByRole('heading', { name: 'Bonificación Q4 switches' })).toBeInTheDocument();
    expect(sellInAPI.detalle).toHaveBeenCalledWith(1);
    expect(screen.getByText('TP-Link')).toBeInTheDocument();
    expect(screen.getByText('Reparto proporcional')).toBeInTheDocument();
    expect(screen.getByText('Switch 16 bocas')).toBeInTheDocument();
    expect(screen.getByText('$ 225,00')).toBeInTheDocument();
  });

  it('lists every Compras operation the purchase is linked to', async () => {
    sellInAPI.detalle.mockResolvedValue({ data: COMPRA_CON_OPERACIONES });
    renderPanel();
    const campo = (await screen.findByText('Operaciones de compra')).closest('div');
    expect(campo).toHaveTextContent('N° 15, N° 16');
  });

  it('shows the FX rate of a USD purchase', async () => {
    sellInAPI.detalle.mockResolvedValue({ data: COMPRA_USD_ANULADA });
    renderPanel();
    expect(await screen.findByText('1.250,50')).toBeInTheDocument();
  });

  it('voids after an inline confirmation, with the reason', async () => {
    const user = userEvent.setup();
    const { onChanged } = renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular' }));
    await user.type(screen.getByLabelText('Motivo (opcional)'), 'Cargada dos veces');
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));
    expect(sellInAPI.anular).toHaveBeenCalledWith(1, 'Cargada dos veces');
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(ANULADA));
    expect(await screen.findByText('Anulada')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Anular' })).not.toBeInTheDocument();
  });

  it('cancelling the confirmation voids nothing', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular' }));
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByRole('button', { name: 'Confirmar anulación' })).not.toBeInTheDocument();
    expect(sellInAPI.anular).not.toHaveBeenCalled();
  });

  it('offers no void without sell_in.gestionar, nor on a voided purchase', async () => {
    renderPanel({ puedeGestionar: false });
    await screen.findByRole('heading', { name: 'Bonificación Q4 switches' });
    expect(screen.queryByRole('button', { name: 'Anular' })).not.toBeInTheDocument();
  });

  it('offers no void on a voided purchase', async () => {
    sellInAPI.detalle.mockResolvedValue({ data: COMPRA_USD_ANULADA });
    renderPanel();
    await screen.findByRole('heading', { name: 'Descuento access points' });
    expect(screen.queryByRole('button', { name: 'Anular' })).not.toBeInTheDocument();
  });

  it('shows the message of a refused void', async () => {
    const user = userEvent.setup();
    sellInAPI.anular.mockRejectedValue({
      response: { status: 409, data: { error: { code: 'CONFLICT', message: 'La compra 1 ya está anulada' } } },
    });
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La compra 1 ya está anulada');
  });

  it('a void that answers after switching purchases never shows on the new one', async () => {
    const user = userEvent.setup();
    sellInAPI.detalle.mockImplementation(porId);
    let responder;
    sellInAPI.anular.mockReturnValue(new Promise((resolve) => (responder = resolve)));
    const { onChanged, cambiarA } = renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));
    cambiarA(3);
    expect(await screen.findByRole('heading', { name: 'Otra compra' })).toBeInTheDocument();
    responder({ data: ANULADA });
    // The void did happen, so the list reloads; the panel keeps showing purchase 3 as it is.
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(ANULADA));
    expect(screen.getByRole('heading', { name: 'Otra compra' })).toBeInTheDocument();
    expect(screen.getByText('Activa')).toBeInTheDocument();
    expect(screen.queryByText('Anulada')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Anular' })).toBeEnabled();
  });

  it('a void refused after switching purchases shows no stale error', async () => {
    const user = userEvent.setup();
    sellInAPI.detalle.mockImplementation(porId);
    let rechazar;
    sellInAPI.anular.mockReturnValue(new Promise((_, reject) => (rechazar = reject)));
    const { cambiarA } = renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));
    cambiarA(3);
    await screen.findByRole('heading', { name: 'Otra compra' });
    rechazar({ response: { status: 409, data: { error: { message: 'La compra 1 ya está anulada' } } } });
    await waitFor(() => expect(sellInAPI.anular).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('the reason typed for one purchase is not carried to the next one', async () => {
    const user = userEvent.setup();
    sellInAPI.detalle.mockImplementation(porId);
    const { cambiarA } = renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular' }));
    await user.type(screen.getByLabelText('Motivo (opcional)'), 'Cargada dos veces');
    cambiarA(3);
    await screen.findByRole('heading', { name: 'Otra compra' });
    expect(screen.queryByLabelText('Motivo (opcional)')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Anular' }));
    expect(screen.getByLabelText('Motivo (opcional)')).toHaveValue('');
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));
    expect(sellInAPI.anular).toHaveBeenCalledWith(3, '');
  });

  it('a purchase generated by a brand bonus is marked and cannot be voided here', async () => {
    sellInAPI.detalle.mockResolvedValue({ data: COMPRA_BONO });
    renderPanel();
    expect(await screen.findByText('Bono de marca')).toBeInTheDocument();
    expect(screen.getByText(/se anula desde su bono/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Anular' })).not.toBeInTheDocument();
  });
});
