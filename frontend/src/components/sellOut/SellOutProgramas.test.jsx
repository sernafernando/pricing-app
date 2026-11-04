import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SellOutProgramas from './SellOutProgramas';
import { sellOutAPI, sellOutProgramasAPI } from '../../services/sellOutAPI';
import { CAMPANAS_DEL_PROGRAMA, PROGRAMA_ARCHIVADO, PROGRAMA_MARCA } from './sellOutFixtures';

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn() },
  sellOutProgramasAPI: { crear: vi.fn(), editar: vi.fn(), asignar: vi.fn() },
}));

const PROGRAMA_VACIO = { ...PROGRAMA_MARCA, id: 9, nombre: 'MARCA Q1', campanas: 0, activas: 0, nombres: 0, desde: null, hasta: null };
const PROGRAMAS = [PROGRAMA_MARCA, PROGRAMA_ARCHIVADO, PROGRAMA_VACIO];

function renderProgramas(props = {}) {
  const onCambio = vi.fn();
  const onVerCampanas = vi.fn();
  render(<SellOutProgramas programas={PROGRAMAS} puedeGestionar onCambio={onCambio} onVerCampanas={onVerCampanas} {...props} />);
  return { onCambio, onVerCampanas };
}

const filaDe = (nombre) => screen.getByRole('row', { name: new RegExp(nombre) });

beforeEach(() => {
  vi.clearAllMocks();
  sellOutAPI.listar.mockResolvedValue({ data: CAMPANAS_DEL_PROGRAMA });
});

describe('SellOutProgramas', () => {
  it('says the program is the top level and lists the active programs with what their campaigns span', () => {
    renderProgramas();

    expect(
      screen.getByText(
        'Programa es el nivel superior: agrupa una campaña y sus repeticiones a lo largo de los quarters. Cada campaña es el monto de un período sobre un alcance; Renovar crea la del quarter siguiente en el mismo programa.',
      ),
    ).toBeInTheDocument();
    const celdas = (nombre) => within(filaDe(nombre)).getAllByRole('cell').map((c) => c.textContent);
    // Campañas, Activas, Nombres distintos, Vigencia, Estado
    expect(celdas('MARCA PROG').slice(1, 6)).toEqual(['3', '2', '2', '01/08/2026 – 31/10/2026', 'Activo']);
    expect(celdas('MARCA Q1').slice(1, 6)).toEqual(['0', '0', '0', 'Sin campañas', 'Activo']);
    expect(screen.queryByRole('row', { name: /Modelos SP/ })).not.toBeInTheDocument();
  });

  it('"Archivados" shows only the archived programs and the search narrows by name', async () => {
    const user = userEvent.setup();
    renderProgramas();

    await user.click(screen.getByRole('button', { name: 'Archivados' }));
    expect(filaDe('Modelos SP')).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: /MARCA PROG/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Todos' }));
    await user.type(screen.getByLabelText('Buscar programa'), 'marca  q1');
    expect(filaDe('MARCA Q1')).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: /MARCA PROG/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('row', { name: /Modelos SP/ })).not.toBeInTheDocument();
  });

  it('"Nuevo programa" creates it with its name and description and reloads the programs', async () => {
    const user = userEvent.setup();
    sellOutProgramasAPI.crear.mockResolvedValue({ data: { ...PROGRAMA_VACIO, id: 10, nombre: 'MARCA Q2' } });
    const { onCambio } = renderProgramas();

    await user.click(screen.getByRole('button', { name: 'Nuevo programa' }));
    const dialogo = screen.getByRole('dialog', { name: 'Nuevo programa' });
    await user.type(within(dialogo).getByLabelText('Nombre'), '  MARCA Q2 ');
    await user.type(within(dialogo).getByLabelText('Descripción (opcional)'), 'Renovación de MARCA PROG');
    await user.click(within(dialogo).getByRole('button', { name: 'Crear programa' }));

    expect(sellOutProgramasAPI.crear).toHaveBeenCalledWith({ nombre: 'MARCA Q2', descripcion: 'Renovación de MARCA PROG' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(onCambio).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveTextContent('Programa «MARCA Q2» creado.');
  });

  it("a refused create shows the API's reason in the dialog, which stays open", async () => {
    const user = userEvent.setup();
    sellOutProgramasAPI.crear.mockRejectedValue({ response: { status: 409, data: { detail: 'Ya existe un programa con ese nombre.' } } });
    const { onCambio } = renderProgramas();

    await user.click(screen.getByRole('button', { name: 'Nuevo programa' }));
    const dialogo = screen.getByRole('dialog', { name: 'Nuevo programa' });
    await user.type(within(dialogo).getByLabelText('Nombre'), 'MARCA PROG');
    await user.click(within(dialogo).getByRole('button', { name: 'Crear programa' }));

    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('Ya existe un programa con ese nombre.');
    expect(onCambio).not.toHaveBeenCalled();
  });

  it('"Editar" sends only the fields that changed', async () => {
    const user = userEvent.setup();
    sellOutProgramasAPI.editar.mockResolvedValue({ data: { ...PROGRAMA_MARCA, nombre: 'MARCA PROG 2026' } });
    const { onCambio } = renderProgramas();

    await user.click(within(filaDe('MARCA PROG')).getByRole('button', { name: 'Editar' }));
    const dialogo = screen.getByRole('dialog', { name: 'Editar programa' });
    expect(within(dialogo).getByLabelText('Nombre')).toHaveValue('MARCA PROG');
    await user.type(within(dialogo).getByLabelText('Nombre'), ' 2026');
    await user.click(within(dialogo).getByRole('button', { name: 'Guardar' }));

    expect(sellOutProgramasAPI.editar).toHaveBeenCalledWith(7, { nombre: 'MARCA PROG 2026' });
    await waitFor(() => expect(onCambio).toHaveBeenCalledTimes(1));
  });

  it('"Archivar" archives an active program and "Reactivar" brings an archived one back', async () => {
    const user = userEvent.setup();
    sellOutProgramasAPI.editar.mockResolvedValue({ data: {} });
    const { onCambio } = renderProgramas();

    await user.click(within(filaDe('MARCA PROG')).getByRole('button', { name: 'Archivar' }));
    expect(sellOutProgramasAPI.editar).toHaveBeenCalledWith(7, { estado: 'archivado' });
    await waitFor(() => expect(onCambio).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('button', { name: 'Archivados' }));
    await user.click(within(filaDe('Modelos SP')).getByRole('button', { name: 'Reactivar' }));
    expect(sellOutProgramasAPI.editar).toHaveBeenLastCalledWith(8, { estado: 'activo' });
  });

  it("expanding a program lists its campaigns, and the selected ones can be taken out of it", async () => {
    const user = userEvent.setup();
    sellOutProgramasAPI.asignar.mockResolvedValue({ data: { asignadas: 2, sin_cambio: 0 } });
    const { onCambio } = renderProgramas();

    await user.click(within(filaDe('MARCA PROG')).getByRole('button', { name: 'Ver campañas de MARCA PROG' }));
    expect(sellOutAPI.listar).toHaveBeenCalledWith({ programa_id: 7, page: 1, page_size: 200 });
    await user.click(await screen.findByRole('checkbox', { name: 'Seleccionar MARCA PROG 3.0' }));
    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar MARCA PROGRAM1' }));
    expect(screen.getByText('2 seleccionadas')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Quitar del programa' }));

    expect(sellOutProgramasAPI.asignar).toHaveBeenCalledWith([71, 72], null);
    await waitFor(() => expect(onCambio).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('status')).toHaveTextContent('2 campañas quitadas de «MARCA PROG».');
  });

  it('"Mover a otro programa" opens the assign dialog with the selected campaigns', async () => {
    const user = userEvent.setup();
    renderProgramas();

    await user.click(within(filaDe('MARCA PROG')).getByRole('button', { name: 'Ver campañas de MARCA PROG' }));
    await user.click(await screen.findByRole('checkbox', { name: 'Seleccionar MARCA PROG 3.0' }));
    await user.click(screen.getByRole('button', { name: 'Mover a otro programa' }));

    expect(screen.getByRole('dialog', { name: 'Asignar a programa (1 campaña)' })).toBeInTheDocument();
  });

  it('"Ver en Campañas" hands the program to the campaigns list', async () => {
    const user = userEvent.setup();
    const { onVerCampanas } = renderProgramas();

    await user.click(within(filaDe('MARCA PROG')).getByRole('button', { name: 'Ver campañas de MARCA PROG' }));
    await user.click(await screen.findByRole('button', { name: 'Ver en Campañas' }));

    expect(onVerCampanas).toHaveBeenCalledWith(7);
  });

  it('without sell_out.gestionar it only shows: no create, edit, archive or selection', async () => {
    const user = userEvent.setup();
    renderProgramas({ puedeGestionar: false });

    expect(screen.queryByRole('button', { name: 'Nuevo programa' })).not.toBeInTheDocument();
    expect(within(filaDe('MARCA PROG')).queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
    expect(within(filaDe('MARCA PROG')).queryByRole('button', { name: 'Archivar' })).not.toBeInTheDocument();
    await user.click(within(filaDe('MARCA PROG')).getByRole('button', { name: 'Ver campañas de MARCA PROG' }));
    await screen.findByText('MARCA PROG 3.0');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
});
