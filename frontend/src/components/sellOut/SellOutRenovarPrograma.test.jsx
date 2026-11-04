/**
 * SellOutRenovarPrograma: "Renovar programa" (Stitch 26104b54). It reads the preview (`GET /{id}/renovacion`), shows
 * the source period and the target quarter, the campaigns it copies (with their source id), the skipped ones with why
 * and the ones left for a later pass, and creates them all or none (`POST /{id}/renovar`).
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sellOutProgramasAPI } from '../../services/sellOutAPI';
import { PROGRAMA_MARCA, RENOVACION_MARCA } from './sellOutFixtures';
import SellOutRenovarPrograma from './SellOutRenovarPrograma';

vi.mock('../../services/sellOutAPI', () => ({
  sellOutProgramasAPI: { renovacion: vi.fn(), renovar: vi.fn() },
}));

function renderRenovar() {
  const onClose = vi.fn();
  const onRenovado = vi.fn();
  render(<SellOutRenovarPrograma programa={PROGRAMA_MARCA} onClose={onClose} onRenovado={onRenovado} />);
  return { onClose, onRenovado };
}

const dialogo = () => screen.getByRole('dialog', { name: 'Renovar programa «MARCA PROG»' });

beforeEach(() => {
  vi.clearAllMocks();
  sellOutProgramasAPI.renovacion.mockResolvedValue({ data: RENOVACION_MARCA });
});

describe('SellOutRenovarPrograma', () => {
  it('shows the preview: periods, the copies with their source id and new dates, the skipped and the left-out ones', async () => {
    renderRenovar();

    expect(sellOutProgramasAPI.renovacion).toHaveBeenCalledWith(7);
    const modal = dialogo();
    expect(
      await within(modal).findByText('Renueva las campañas de Oct–Dic 2026 al trimestre Ene–Mar 2027 (01/01/2027 – 31/03/2027).'),
    ).toBeInTheDocument();
    const periodos = within(modal).getByRole('group', { name: 'Períodos' });
    expect(within(periodos).getByText('Oct–Dic 2026')).toBeInTheDocument();
    expect(within(periodos).getByText('01/10/2026 – 31/12/2026')).toBeInTheDocument();
    expect(within(periodos).getByText('Ene–Mar 2027')).toBeInTheDocument();

    const crear = within(modal).getByRole('list', { name: 'Se crearán 2' });
    const filas = within(crear).getAllByRole('listitem');
    expect(filas).toHaveLength(2);
    expect(filas[0]).toHaveTextContent('Modelo A Q4 2026');
    expect(filas[0]).toHaveTextContent('Modelo A Q1 2027');
    expect(filas[0]).toHaveTextContent('01/01/2027 – 31/03/2027');
    expect(within(filas[0]).getByText('ID #11')).toBeInTheDocument();
    expect(within(filas[1]).getByText('ID #12')).toBeInTheDocument();

    const omitidas = within(modal).getByRole('list', { name: 'Se omiten 2' });
    const [anulada, renovada] = within(omitidas).getAllByRole('listitem');
    expect(anulada).toHaveTextContent('Modelo C Q4 2026 — anulada, no se renueva');
    expect(within(anulada).getByText('Campaña anulada')).toBeInTheDocument();
    expect(renovada).toHaveTextContent('Modelo D Q4 2026 — ya renovada en la campaña 812 (Modelo D Q1 2027)');
    expect(within(renovada).getByText('Copia existente')).toBeInTheDocument();

    expect(within(modal).getByText(/Quedan afuera de esta renovación/)).toHaveTextContent(
      'Quedan afuera de esta renovación 1 campaña activa sin renovar de Ene–Mar 2027: Modelo E Q1 2027. Se renuevan en una próxima pasada.',
    );
    expect(
      within(modal).getByText('Se crea todo o nada. Cada campaña nueva queda en el mismo programa y se puede editar después.'),
    ).toBeInTheDocument();
    expect(within(modal).getByText('2 campañas listas para renovar')).toBeInTheDocument();
    expect(within(modal).queryByText(/LOTE/)).not.toBeInTheDocument();
  });

  it('"Renovar N campañas" sends the previewed ids and reports what it created', async () => {
    const user = userEvent.setup();
    sellOutProgramasAPI.renovar.mockResolvedValue({
      data: { creadas: [{ campana_id: 11, nueva_id: 901 }, { campana_id: 12, nueva_id: 902 }], omitidas: RENOVACION_MARCA.omitidas },
    });
    const { onRenovado } = renderRenovar();

    await user.click(await within(dialogo()).findByRole('button', { name: 'Renovar 2 campañas' }));

    expect(sellOutProgramasAPI.renovar).toHaveBeenCalledWith(7, [11, 12]);
    await waitFor(() => expect(onRenovado).toHaveBeenCalledWith('2 campañas renovadas en «MARCA PROG» para Ene–Mar 2027.'));
  });

  it('a 409 (the preview changed) shows why, creates nothing and reads the preview again', async () => {
    const user = userEvent.setup();
    const mensaje = 'La renovación del programa cambió desde la vista previa: no se creó ninguna campaña. Revisala de nuevo.';
    sellOutProgramasAPI.renovar.mockRejectedValue({ response: { status: 409, data: { error: { message: mensaje } } } });
    const { onRenovado } = renderRenovar();

    await user.click(await within(dialogo()).findByRole('button', { name: 'Renovar 2 campañas' }));

    expect(await within(dialogo()).findByRole('alert')).toHaveTextContent(mensaje);
    await waitFor(() => expect(sellOutProgramasAPI.renovacion).toHaveBeenCalledTimes(2));
    expect(onRenovado).not.toHaveBeenCalled();
  });

  it('a refused renewal (422) shows the reason and keeps the dialog open', async () => {
    const user = userEvent.setup();
    const mensaje = 'No se renovó ninguna campaña: la campaña 11 (Modelo A Q4 2026): demasiados productos.';
    sellOutProgramasAPI.renovar.mockRejectedValue({ response: { status: 422, data: { error: { message: mensaje } } } });
    const { onRenovado } = renderRenovar();

    await user.click(await within(dialogo()).findByRole('button', { name: 'Renovar 2 campañas' }));

    expect(await within(dialogo()).findByRole('alert')).toHaveTextContent(mensaje);
    expect(sellOutProgramasAPI.renovacion).toHaveBeenCalledTimes(1);
    expect(onRenovado).not.toHaveBeenCalled();
  });

  it('with nothing to renew it says so and cannot confirm', async () => {
    sellOutProgramasAPI.renovacion.mockResolvedValue({
      data: { ...RENOVACION_MARCA, renovar: [], quedan_afuera: [] },
    });
    renderRenovar();

    expect(await within(dialogo()).findByText('No hay campañas para renovar en este programa.')).toBeInTheDocument();
    expect(within(dialogo()).getByRole('button', { name: 'Renovar' })).toBeDisabled();
    expect(within(dialogo()).getByRole('list', { name: 'Se omiten 2' })).toBeInTheDocument();
  });

  it('a preview that cannot be read shows the reason and only lets you close', async () => {
    const user = userEvent.setup();
    sellOutProgramasAPI.renovacion.mockRejectedValue({
      response: { status: 422, data: { error: { message: 'El programa «MARCA PROG» está archivado.' } } },
    });
    const { onClose } = renderRenovar();

    expect(await within(dialogo()).findByRole('alert')).toHaveTextContent('El programa «MARCA PROG» está archivado.');
    expect(within(dialogo()).getByRole('button', { name: 'Renovar' })).toBeDisabled();
    await user.click(within(dialogo()).getByRole('button', { name: 'Cancelar' }));
    expect(onClose).toHaveBeenCalled();
  });
});
