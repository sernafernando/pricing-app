import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { sellInBonosAPI } from '../../services/sellInAPI';
import { BONO, BONO_ANULADO } from './sellInFixtures';
import SellInBonoPanel from './SellInBonoPanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInBonosAPI: { detalle: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
}));

const MARCAS = ['MERCUSYS', 'TP-LINK'];
const apiError = (status, message) => Object.assign(new Error(message), { response: { status, data: { error: { message } } } });

beforeEach(() => {
  vi.clearAllMocks();
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO });
  sellInBonosAPI.crear.mockResolvedValue({ data: { ...BONO, id: 9 } });
  sellInBonosAPI.editar.mockResolvedValue({ data: { ...BONO, monto_unit: '4.00' } });
  sellInBonosAPI.anular.mockResolvedValue({ data: { ...BONO, estado: 'anulada' } });
});

const renderPanel = (props = {}) => {
  const handlers = { onSaved: vi.fn(), onClose: vi.fn() };
  render(<SellInBonoPanel bonoId={3} marcas={MARCAS} puedeGestionar {...handlers} {...props} />);
  return handlers;
};

const llenar = async (user) => {
  await user.selectOptions(screen.getByLabelText('Marca'), 'TP-LINK');
  await user.type(screen.getByLabelText('Monto por unidad'), '3');
  await user.type(screen.getByLabelText('Factura desde'), '2026-09-01');
  await user.type(screen.getByLabelText('Factura hasta'), '2026-11-30');
  await user.type(screen.getByLabelText('Descripción'), 'Bono TP-Link');
};

describe('SellInBonoPanel — new bonus', () => {
  it('creates a bonus in USD by default with the brand, amount per unit and invoice range', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderPanel({ bonoId: null });
    expect(screen.getByRole('heading', { name: 'Nuevo sell in · Bono de marca' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'USD' })).toHaveAttribute('aria-pressed', 'true');
    await llenar(user);
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));
    expect(sellInBonosAPI.crear).toHaveBeenCalledWith({
      marca: 'TP-LINK',
      monto_unit: '3',
      moneda: 'USD',
      fecha_desde: '2026-09-01',
      fecha_hasta: '2026-11-30',
      descripcion: 'Bono TP-Link',
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ ...BONO, id: 9 }));
    expect(sellInBonosAPI.detalle).not.toHaveBeenCalled();
  });

  it('offers only the brands of the brand filter', () => {
    renderPanel({ bonoId: null });
    const opciones = within(screen.getByLabelText('Marca')).getAllByRole('option').map((o) => o.value);
    expect(opciones).toEqual(['', 'MERCUSYS', 'TP-LINK']);
  });

  it('shows the backend message inline when it refuses the bonus', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.crear.mockRejectedValue(apiError(422, 'La fecha desde no puede ser posterior a la fecha hasta'));
    const { onSaved } = renderPanel({ bonoId: null });
    await llenar(user);
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La fecha desde no puede ser posterior a la fecha hasta');
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('asks for the missing data before calling the backend', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Faltan datos');
    expect(sellInBonosAPI.crear).not.toHaveBeenCalled();
  });
});

describe('SellInBonoPanel — existing bonus', () => {
  it('loads the bonus with what it generated so far', async () => {
    renderPanel();
    expect(await screen.findByRole('heading', { name: 'Bono TP-Link USD 3/u' })).toBeInTheDocument();
    expect(sellInBonosAPI.detalle).toHaveBeenCalledWith(3);
    expect(screen.getByText('Bono de marca')).toBeInTheDocument();
    expect(screen.getByText('18 compras · 1.040 u · USD 3.120,00 aplicados')).toBeInTheDocument();
    expect(screen.getByLabelText('Marca')).toHaveValue('TP-LINK');
  });

  it('saves an edit as a full replace', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderPanel();
    const monto = await screen.findByLabelText('Monto por unidad');
    await user.clear(monto);
    await user.type(monto, '4');
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    expect(sellInBonosAPI.editar).toHaveBeenCalledWith(3, {
      marca: 'TP-LINK',
      monto_unit: '4',
      moneda: 'USD',
      fecha_desde: '2026-09-01',
      fecha_hasta: '2026-11-30',
      descripcion: 'Bono TP-Link USD 3/u',
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ ...BONO, monto_unit: '4.00' }));
  });

  it('shows the backend message inline when an edit is refused', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.editar.mockRejectedValue(apiError(409, 'El bono 3 está anulado'));
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Guardar cambios' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('El bono 3 está anulado');
  });

  it('voids after an inline confirmation with the reason, and shows the 409 if it was already voided', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular bono' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Motivo (opcional)'), 'Acuerdo caído');
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));
    expect(sellInBonosAPI.anular).toHaveBeenCalledWith(3, 'Acuerdo caído');
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ ...BONO, estado: 'anulada' }));
    expect(await screen.findByText('Anulado')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Anular bono' })).not.toBeInTheDocument();
  });

  it('shows the backend message when voiding is refused', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.anular.mockRejectedValue(apiError(409, 'El bono 3 ya está anulado'));
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular bono' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('El bono 3 ya está anulado');
  });

  it('is read-only without sell_in.gestionar', async () => {
    renderPanel({ puedeGestionar: false });
    expect(await screen.findByLabelText('Monto por unidad')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Guardar cambios' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Anular bono' })).not.toBeInTheDocument();
  });

  it('a voided bonus is read-only', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: BONO_ANULADO });
    renderPanel({ bonoId: 4 });
    expect(await screen.findByText('Anulado')).toBeInTheDocument();
    expect(screen.getByLabelText('Monto por unidad')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Guardar cambios' })).not.toBeInTheDocument();
  });

  it('keeps a brand that is not in the filter list', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: { ...BONO, marca: 'VIEJA' } });
    renderPanel();
    await waitFor(() => expect(screen.getByLabelText('Marca')).toHaveValue('VIEJA'));
  });

  it('shows a load error inline', async () => {
    sellInBonosAPI.detalle.mockRejectedValue(apiError(404, 'El bono 3 no existe'));
    renderPanel();
    expect(await screen.findByRole('alert')).toHaveTextContent('El bono 3 no existe');
  });

  it('shows the creation date in the local (Argentina) day, not the UTC one', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: { ...BONO, created_at: '2026-08-28T02:00:00+00:00' } });
    renderPanel();
    expect(await screen.findByText('Creado el 27/8/2026')).toBeInTheDocument();
  });

  it('cancelling the void confirmation clears the reason', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular bono' }));
    await user.type(screen.getByLabelText('Motivo (opcional)'), 'Acuerdo caído');
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    await user.click(screen.getByRole('button', { name: 'Anular bono' }));
    expect(screen.getByLabelText('Motivo (opcional)')).toHaveValue('');
  });

  it('a 409 on save (voided by someone else) reloads the bonus and shows it read-only', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.editar.mockRejectedValue(apiError(409, 'El bono 3 está anulado'));
    sellInBonosAPI.detalle.mockResolvedValueOnce({ data: BONO }).mockResolvedValueOnce({ data: { ...BONO, estado: 'anulada' } });
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Guardar cambios' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('El bono 3 está anulado');
    expect(await screen.findByText('Anulado')).toBeInTheDocument();
    expect(sellInBonosAPI.detalle).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText('Monto por unidad')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Guardar cambios' })).not.toBeInTheDocument();
  });
});
