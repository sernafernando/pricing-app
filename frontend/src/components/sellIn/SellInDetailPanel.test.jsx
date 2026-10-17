import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { sellInAPI } from '../../services/sellInAPI';
import { COMPRA_ARS, COMPRA_USD_ANULADA } from './sellInFixtures';
import SellInDetailPanel from './SellInDetailPanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { detalle: vi.fn(), anular: vi.fn() },
}));

const ANULADA = { ...COMPRA_ARS, estado: 'anulada', aplica: false };

beforeEach(() => {
  vi.clearAllMocks();
  sellInAPI.detalle.mockResolvedValue({ data: COMPRA_ARS });
  sellInAPI.anular.mockResolvedValue({ data: ANULADA });
});

const renderPanel = (props = {}) => {
  const onChanged = vi.fn();
  render(<SellInDetailPanel compraId={1} puedeGestionar onChanged={onChanged} onClose={vi.fn()} {...props} />);
  return { onChanged };
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
});
