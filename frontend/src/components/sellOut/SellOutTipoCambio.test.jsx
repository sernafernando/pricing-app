/**
 * SellOutTipoCambio: the rate the brand paid at, for a USD `al_cobro` campaign (T8c). Until it is set, ARS
 * amounts are estimated with the day's BNA rate; it can be set, and changed, also after the campaign ended.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CAMPANA_MIGRADA } from './sellOutFixtures';
import SellOutTipoCambio from './SellOutTipoCambio';

vi.mock('../../services/sellOutAPI', () => ({ sellOutAPI: { definirTipoCambio: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe('SellOutTipoCambio', () => {
  it('not set yet: says the BNA estimate is used, sets it and hands back the campaign', async () => {
    const user = userEvent.setup();
    const onDefinido = vi.fn();
    const definida = { ...CAMPANA_MIGRADA, tipo_cambio: '1420.000000', tc_definido_en: '2026-10-22T18:00:00Z' };
    sellOutAPI.definirTipoCambio.mockResolvedValue({ data: definida });
    render(<SellOutTipoCambio campana={CAMPANA_MIGRADA} onDefinido={onDefinido} />);

    expect(screen.getByText(/Sin definir/)).toHaveTextContent('se estiman con el dólar BNA del día');
    await user.type(screen.getByLabelText('Valor del tipo de cambio'), '1420');
    await user.click(screen.getByRole('button', { name: 'Definir tipo de cambio' }));

    expect(sellOutAPI.definirTipoCambio).toHaveBeenCalledWith(55, '1420');
    expect(onDefinido).toHaveBeenCalledWith(definida);
  });

  it('already set: shows it and offers to change it', () => {
    render(<SellOutTipoCambio campana={{ ...CAMPANA_MIGRADA, tipo_cambio: '1420.000000', tc_definido_en: '2026-10-22T18:00:00Z' }} onDefinido={() => {}} />);
    expect(screen.getByText(/Definido/)).toHaveTextContent('1.420,00');
    expect(screen.getByRole('button', { name: 'Cambiar tipo de cambio' })).toBeInTheDocument();
  });

  it('refuses an empty or non-positive rate without calling the API, and shows the backend message', async () => {
    const user = userEvent.setup();
    render(<SellOutTipoCambio campana={CAMPANA_MIGRADA} onDefinido={() => {}} />);
    await user.click(screen.getByRole('button', { name: 'Definir tipo de cambio' }));
    expect(screen.getByRole('alert')).toHaveTextContent('El tipo de cambio tiene que ser mayor a 0.');
    expect(sellOutAPI.definirTipoCambio).not.toHaveBeenCalled();

    sellOutAPI.definirTipoCambio.mockRejectedValue({ response: { status: 409, data: { detail: 'La campaña está anulada' } } });
    await user.type(screen.getByLabelText('Valor del tipo de cambio'), '1400');
    await user.click(screen.getByRole('button', { name: 'Definir tipo de cambio' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La campaña está anulada');
  });
});
