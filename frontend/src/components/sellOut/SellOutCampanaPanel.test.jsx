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

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), crear: vi.fn(), editar: vi.fn() },
}));

const GRUPOS = [
  { id: 1, nombre: 'TP-Link redes' },
  { id: 301, nombre: 'Offset #48: RB 8180' },
];

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

describe('SellOutCampanaPanel — create and edit (T8b)', () => {
  it('a new campaign: fills the form, sends SellOutCampanaIn and hands back what was created', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    sellOutAPI.crear.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, id: 95 } });
    render(<SellOutCampanaPanel campanaId={null} grupos={GRUPOS} puedeGestionar onSaved={onSaved} onClose={() => {}} />);

    expect(screen.getByRole('heading', { name: 'Nueva campaña de sell out' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Nombre'), 'Epson diciembre');
    await user.type(screen.getByLabelText('Monto por unidad'), '12');
    await user.type(screen.getByLabelText('Desde'), '2026-12-01');
    await user.type(screen.getByLabelText('Hasta'), '2026-12-31');
    await user.click(screen.getByRole('checkbox', { name: 'TP-Link redes' }));
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));

    expect(sellOutAPI.crear).toHaveBeenCalledWith(
      expect.objectContaining({
        nombre: 'Epson diciembre',
        tipo: 'por_unidad',
        monto_unit: '12',
        fecha_desde: '2026-12-01',
        fecha_hasta: '2026-12-31',
        moneda: 'USD',
        tc_modo: 'al_cobro',
        grupo_ids: [1],
      }),
    );
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ id: 95 }));
  });

  it('says what is missing and sends nothing', async () => {
    const user = userEvent.setup();
    render(<SellOutCampanaPanel campanaId={null} grupos={GRUPOS} puedeGestionar onSaved={() => {}} onClose={() => {}} />);
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Faltan datos: nombre, fechas, monto por unidad, productos alcanzados.');
    expect(sellOutAPI.crear).not.toHaveBeenCalled();
  });

  it('a percentage in ARS asks for the base and hides the exchange rate; a fixed USD rate asks for it', async () => {
    const user = userEvent.setup();
    render(<SellOutCampanaPanel campanaId={null} grupos={GRUPOS} puedeGestionar onSaved={() => {}} onClose={() => {}} />);
    expect(screen.queryByLabelText('Tipo de cambio fijo')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Tipo de cambio'), 'fijo');
    expect(screen.getByLabelText('Tipo de cambio fijo')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Porcentaje' }));
    await user.click(screen.getByRole('button', { name: 'ARS' }));
    expect(screen.getByLabelText('Porcentaje')).toBeInTheDocument();
    expect(screen.getByLabelText('Base del porcentaje')).toBeInTheDocument();
    expect(screen.queryByLabelText('Tipo de cambio')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Monto por unidad')).not.toBeInTheDocument();
  });

  it('an active campaign with sell_out.gestionar: edits it (full replace) and shows the backend message', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MIGRADA });
    sellOutAPI.editar.mockResolvedValueOnce({ data: { ...CAMPANA_MIGRADA, monto_unit: '24.00' } });
    render(<SellOutCampanaPanel campanaId={55} grupos={GRUPOS} puedeGestionar onSaved={onSaved} onClose={() => {}} />);

    const monto = await screen.findByLabelText('Monto por unidad');
    expect(monto).toHaveValue(36);
    expect(screen.getByRole('checkbox', { name: 'Offset #48: RB 8180' })).toBeChecked();
    await user.clear(monto);
    await user.type(monto, '24');
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    expect(sellOutAPI.editar).toHaveBeenCalledWith(55, expect.objectContaining({ monto_unit: '24', grupo_ids: [301] }));
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ monto_unit: '24.00' }));
    expect(campo('Origen')).toHaveTextContent('Migrada del offset #48');

    sellOutAPI.editar.mockRejectedValueOnce({ response: { status: 422, data: { detail: 'La fecha hasta es anterior a la fecha desde' } } });
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La fecha hasta es anterior a la fecha desde');
  });

  it('a voided campaign stays read-only even with sell_out.gestionar', async () => {
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_PORCENTAJE_ANULADA });
    render(<SellOutCampanaPanel campanaId={60} grupos={GRUPOS} puedeGestionar onSaved={() => {}} onClose={() => {}} />);
    expect(await screen.findByText('Anulada')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Guardar cambios' })).not.toBeInTheDocument();
  });
});
