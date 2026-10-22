/**
 * SellOutCampanaPanel: one sell-out campaign read fresh from the API (T8): its terms, what it credited by
 * channel, its recalculation state, and the legacy offset it came from.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CAMPANA_MIGRADA, CAMPANA_PORCENTAJE_ANULADA } from './sellOutFixtures';
import SellOutCampanaPanel from './SellOutCampanaPanel';

vi.mock('../../services/sellOutAPI', () => ({ sellOutAPI: { listar: vi.fn(), detalle: vi.fn() } }));

const campo = (label) => screen.getByText(label, { selector: 'dt' }).nextElementSibling;

beforeEach(() => vi.clearAllMocks());

describe('SellOutCampanaPanel', () => {
  it('a per-unit USD campaign: its terms, channels and the offset it was migrated from', async () => {
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MIGRADA });
    render(<SellOutCampanaPanel campanaId={55} onClose={() => {}} />);

    expect(await screen.findByRole('heading', { name: 'RB 8180' })).toBeInTheDocument();
    expect(sellOutAPI.detalle).toHaveBeenCalledWith(55);
    expect(screen.getByText('Activa')).toBeInTheDocument();
    expect(campo('Beneficio')).toHaveTextContent('USD 36,00 por unidad');
    expect(campo('Vigencia')).toHaveTextContent('01/01/2026 – 31/12/2026');
    expect(campo('Tipo de cambio')).toHaveTextContent('Al cobro');
    expect(campo('Alcance')).toHaveTextContent('Offset #48: RB 8180');
    expect(campo('Origen')).toHaveTextContent('Migrada del offset #48');
    expect(campo('Recálculo')).toHaveTextContent('Al día');
    expect(screen.getByText('Mercado Libre').closest('tr')).toHaveTextContent('20');
    expect(screen.getByText('Fuera de ML').closest('tr')).toHaveTextContent('USD 360,00');
  });

  it('a voided % campaign: base, caps left, VAT flag and a failed recalculation with its error', async () => {
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_PORCENTAJE_ANULADA });
    render(<SellOutCampanaPanel campanaId={60} onClose={() => {}} />);

    expect(await screen.findByText('Anulada')).toBeInTheDocument();
    expect(campo('Beneficio')).toHaveTextContent('2% del precio neto');
    expect(campo('Topes')).toHaveTextContent('500 u (quedan 470)');
    expect(campo('Topes')).toHaveTextContent('$ 1.000.000,00 (quedan $ 998.920,00)');
    expect(campo('Monto con IVA')).toHaveTextContent('Sí');
    expect(campo('Acumulable')).toHaveTextContent('No');
    expect(campo('Origen')).toHaveTextContent('Cargada a mano');
    expect(campo('Recálculo')).toHaveTextContent('Falló: Falta el tipo de cambio');
    expect(screen.getByText('Todavía no acreditó ventas.')).toBeInTheDocument();
  });

  it('shows the API error and closes', async () => {
    sellOutAPI.detalle.mockRejectedValue({ response: { data: { detail: 'Campaña no encontrada' } } });
    const onClose = vi.fn();
    render(<SellOutCampanaPanel campanaId={99} onClose={onClose} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Campaña no encontrada');
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
