/**
 * SellOutCampanaPanel — renewing a campaign (campaign system, slice B): "Renovar" loads the renewal draft into a NEW
 * campaign form; nothing is saved until "Guardar campaña", and the original stays untouched.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { sellOutAPI } from '../../services/sellOutAPI';
import {
  CAMPANA_MIGRADA,
  CAMPANA_MONTO_TOTAL,
  CAMPANA_PORCENTAJE_ANULADA,
  CONSUMOS_USD,
  RENOVACION_MIGRADA,
  RENOVACION_MONTO_TOTAL,
} from './sellOutFixtures';
import SellOutCampanaPanel from './SellOutCampanaPanel';

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: {
    detalle: vi.fn(),
    crear: vi.fn(),
    editar: vi.fn(),
    anular: vi.fn(),
    renovacion: vi.fn(),
    consumos: vi.fn(),
    repartir: vi.fn(),
    definirTipoCambio: vi.fn(),
  },
}));

const GRUPOS = [
  { id: 1, nombre: 'TP-Link redes' },
  { id: 301, nombre: 'Offset #48: RB 8180' },
];
const NOTA = 'Copia de «RB 8180». Revisá fechas y montos antes de guardar.';

const renderPanel = (campanaId, props = {}) =>
  render(<SellOutCampanaPanel campanaId={campanaId} grupos={GRUPOS} puedeGestionar onSaved={() => {}} onClose={() => {}} {...props} />);

beforeEach(() => {
  vi.clearAllMocks();
  sellOutAPI.consumos.mockResolvedValue({ data: CONSUMOS_USD });
});

describe('SellOutCampanaPanel — Renovar', () => {
  it('opens a new campaign form with the draft; nothing is saved until "Guardar campaña", which creates the copy', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MIGRADA });
    sellOutAPI.renovacion.mockResolvedValue({ data: RENOVACION_MIGRADA });
    sellOutAPI.crear.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, id: 96, fecha_desde: '2027-01-01' } });
    renderPanel(55, { onSaved });

    await user.click(await screen.findByRole('button', { name: 'Renovar' }));
    expect(sellOutAPI.renovacion).toHaveBeenCalledWith(55);
    expect(await screen.findByRole('heading', { name: 'Nueva campaña de sell out' })).toBeInTheDocument();
    expect(screen.getByText(NOTA)).toBeInTheDocument();
    expect(screen.getByLabelText('Nombre')).toHaveValue('RB 8180');
    expect(screen.getByLabelText('Desde')).toHaveValue('2027-01-01');
    expect(screen.getByLabelText('Hasta')).toHaveValue('2027-03-31');
    expect(screen.getByLabelText('Monto por unidad')).toHaveValue(36);
    expect(screen.getByLabelText('Tipo de cambio fijo')).toHaveValue(1400);
    expect(screen.getByRole('checkbox', { name: 'Offset #48: RB 8180' })).toBeChecked();
    expect(screen.queryByRole('button', { name: 'Anular campaña' })).not.toBeInTheDocument();
    expect(sellOutAPI.crear).not.toHaveBeenCalled();
    expect(sellOutAPI.editar).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText('Hasta'));
    await user.type(screen.getByLabelText('Hasta'), '2027-02-28');
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));
    expect(sellOutAPI.crear).toHaveBeenCalledWith(
      expect.objectContaining({
        nombre: 'RB 8180',
        fecha_desde: '2027-01-01',
        fecha_hasta: '2027-02-28',
        tc_modo: 'fijo',
        tipo_cambio: '1400.000000',
        tope_unidades: 500,
        acumulable: false,
        monto_incluye_iva: true,
        grupo_ids: [301],
        items: [{ item_id: 4172, monto_unit: '30.00' }],
        programa_id: 12,
      }),
    );
    expect(sellOutAPI.editar).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ id: 96 }));
  });

  it('a voided campaign can be renewed too', async () => {
    const user = userEvent.setup();
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_PORCENTAJE_ANULADA });
    sellOutAPI.renovacion.mockResolvedValue({ data: { ...RENOVACION_MIGRADA, nombre: 'TP-Link 2% enero' } });
    renderPanel(60);

    await user.click(await screen.findByRole('button', { name: 'Renovar' }));
    expect(await screen.findByText('Copia de «TP-Link 2% noviembre». Revisá fechas y montos antes de guardar.')).toBeInTheDocument();
    expect(screen.getByLabelText('Nombre')).toHaveValue('TP-Link 2% enero');
  });

  it('a monto total campaign says its split is copied when saving, and sends it with the create', async () => {
    const user = userEvent.setup();
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MONTO_TOTAL });
    sellOutAPI.renovacion.mockResolvedValue({ data: RENOVACION_MONTO_TOTAL });
    sellOutAPI.crear.mockResolvedValue({ data: { ...CAMPANA_MONTO_TOTAL, id: 97 } });
    renderPanel(70);

    await user.click(await screen.findByRole('button', { name: 'Renovar' }));
    expect(await screen.findByText('El reparto del monto total (2 productos) se copia al guardar.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));
    expect(sellOutAPI.crear).toHaveBeenCalledWith(
      expect.objectContaining({
        tipo: 'monto_total',
        monto_total: '2000000.00',
        items: [
          { item_id: 4172, reparto_porcentaje: '60.0000', reparto_monto: null },
          { item_id: 4173, reparto_porcentaje: null, reparto_monto: '500000.00' },
        ],
      }),
    );
    expect(sellOutAPI.repartir).not.toHaveBeenCalled();
  });

  it('"Cancelar" goes back to the original campaign without saving anything', async () => {
    const user = userEvent.setup();
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MIGRADA });
    sellOutAPI.renovacion.mockResolvedValue({ data: RENOVACION_MIGRADA });
    renderPanel(55);

    await user.click(await screen.findByRole('button', { name: 'Renovar' }));
    await screen.findByText(NOTA);
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(await screen.findByRole('heading', { name: 'RB 8180' })).toBeInTheDocument();
    expect(screen.queryByText(NOTA)).not.toBeInTheDocument();
    expect(sellOutAPI.crear).not.toHaveBeenCalled();
  });

  it('shows the API message when the draft cannot be read and stays on the campaign', async () => {
    const user = userEvent.setup();
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MIGRADA });
    sellOutAPI.renovacion.mockRejectedValue({ response: { data: { detail: 'La campaña 55 no existe' } } });
    renderPanel(55);

    await user.click(await screen.findByRole('button', { name: 'Renovar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La campaña 55 no existe');
    expect(screen.getByRole('heading', { name: 'RB 8180' })).toBeInTheDocument();
  });

  it('without sell_out.gestionar there is no "Renovar", on an active or a voided campaign', async () => {
    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MIGRADA });
    const { unmount } = renderPanel(55, { puedeGestionar: false });
    expect(await screen.findByRole('heading', { name: 'RB 8180' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Renovar' })).not.toBeInTheDocument();
    unmount();

    sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_PORCENTAJE_ANULADA });
    renderPanel(60, { puedeGestionar: false });
    expect(await screen.findByText('Anulada')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Renovar' })).not.toBeInTheDocument();
  });
});
