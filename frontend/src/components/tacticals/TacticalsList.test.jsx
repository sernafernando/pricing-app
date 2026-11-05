/**
 * Tactical list by brand (owner, 2026-11-04, S7: "el tactical tiene que podersele cargar una marca adjunta para
 * después poder filtrar por marca"). Built from the pending design handoffs/diseno-tactical/listado-tacticals-PENDIENTE.html
 * on the final contract of GET /api/tacticals (handoffs/tactical-tarea.md, "Contrato final"); see tacticalsFixtures.js.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TacticalsList from './TacticalsList';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { TACTICAL_BPS, TACTICAL_REBATE, pagina } from './tacticalsFixtures';

vi.mock('../../services/tacticalsAPI', () => ({ tacticalsAPI: { listar: vi.fn(), editar: vi.fn(), anular: vi.fn() } }));

const BPS = TACTICAL_BPS;
const REBATE = TACTICAL_REBATE;

const MARCAS = ['HP', 'Lenovo', 'TP-Link'];

const filaDe = (nombre) => screen.getByRole('row', { name: new RegExp(nombre) });
const ultimaConsulta = () => tacticalsAPI.listar.mock.calls.at(-1)[0];

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 10, 12, 10));
  tacticalsAPI.listar.mockResolvedValue({ data: pagina([BPS, REBATE], 2) });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('TacticalsList rows', () => {
  it('asks the current tacticals and shows one row per tactical, whose lines open and close', async () => {
    render(<TacticalsList marcas={MARCAS} />);

    expect(await screen.findByText('Tacticals BPS Noviembre Q1FY27')).toBeInTheDocument();
    expect(tacticalsAPI.listar).toHaveBeenCalledWith({ estado: 'vigentes', page: 1, page_size: 50 });
    expect(within(filaDe('Rebate HP Q1FY27')).getByText('ARS 1.240.000')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' }));
    expect(screen.getByText('Líneas del tactical (3)')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ocultar las líneas de Tacticals BPS Noviembre Q1FY27' }));
    expect(screen.queryByText('Líneas del tactical (3)')).not.toBeInTheDocument();
  });
});

describe('TacticalsList filters', () => {
  it('a filter change shows the loading message instead of the previous rows, and closes the open ones', async () => {
    render(<TacticalsList marcas={MARCAS} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' }));

    let responder;
    tacticalsAPI.listar.mockImplementation(() => new Promise((resolve) => (responder = resolve)));
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Marca' }), 'HP');

    expect(screen.getByText('Cargando tacticals…')).toBeInTheDocument();
    expect(screen.queryByText('Tacticals BPS Noviembre Q1FY27')).not.toBeInTheDocument();
    responder({ data: pagina([BPS, REBATE]) });
    expect(await screen.findByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' })).toBeInTheDocument();
  });

  it('sends tipo, brand, state, dates and search, and Limpiar filtros goes back to the current ones', async () => {
    render(<TacticalsList marcas={MARCAS} />);
    await screen.findByText('Tacticals BPS Noviembre Q1FY27');

    await userEvent.click(screen.getByRole('button', { name: 'Sell out' }));
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ tipo: 'sell_out' }));
    await userEvent.selectOptions(screen.getByLabelText('Marca'), 'HP');
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ tipo: 'sell_out', marca: 'HP' }));
    await userEvent.selectOptions(screen.getByLabelText('Moneda'), 'USD');
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ marca: 'HP', moneda: 'USD' }));
    await userEvent.click(screen.getByRole('button', { name: 'Anulados' }));
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ estado: 'anulados' }));
    await userEvent.type(screen.getByLabelText('Desde'), '2026-11-01');
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ desde: '2026-11-01' }));
    await userEvent.type(screen.getByRole('searchbox', { name: 'Buscar por nombre o referencia' }), 'bps');
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ q: 'bps' }));

    await userEvent.click(screen.getByRole('button', { name: 'Limpiar filtros' }));
    await waitFor(() => expect(ultimaConsulta()).toEqual({ estado: 'vigentes', page: 1, page_size: 50 }));
    expect(screen.getByLabelText('Marca')).toHaveValue('');
    expect(screen.getByLabelText('Moneda')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Vigentes' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('a filter change that leaves the same query keeps the list and its open rows', async () => {
    render(<TacticalsList marcas={MARCAS} />);
    const buscar = screen.getByRole('searchbox', { name: 'Buscar por nombre o referencia' });
    await screen.findByText('Tacticals BPS Noviembre Q1FY27');
    await userEvent.type(buscar, 'bps');
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ q: 'bps' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' }));
    const pedidos = tacticalsAPI.listar.mock.calls.length;

    await userEvent.type(buscar, ' ');
    await new Promise((resolve) => setTimeout(resolve, 400));

    expect(screen.queryByText('Cargando tacticals…')).not.toBeInTheDocument();
    expect(screen.getByText('Líneas del tactical (3)')).toBeInTheDocument();
    expect(tacticalsAPI.listar).toHaveBeenCalledTimes(pedidos);
  });
});

describe('TacticalsList paging', () => {
  it('a reload that leaves the page past the end goes to the last page with tacticals', async () => {
    const muchos = Array.from({ length: 25 }, (_, i) => ({ ...REBATE, id: 100 + i, nombre: `Rebate ${i + 1}` }));
    tacticalsAPI.listar.mockImplementation(async ({ page }) => ({
      data: page === 1 ? pagina(muchos, 26) : pagina([{ ...REBATE, id: 200, nombre: 'Rebate 26' }], 26, 2),
    }));
    const { rerender } = render(<TacticalsList marcas={MARCAS} />);
    await screen.findByText('Rebate 1');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /filas/i }), '25');
    await userEvent.click(screen.getByRole('button', { name: /siguiente/i }));
    expect(await screen.findByText('Rebate 26')).toBeInTheDocument();

    tacticalsAPI.listar.mockImplementation(async ({ page }) => ({
      data: page === 1 ? pagina(muchos, 25) : pagina([], 25, 2),
    }));
    rerender(<TacticalsList marcas={MARCAS} version={1} />);

    expect(await screen.findByText('Rebate 1')).toBeInTheDocument();
    expect(ultimaConsulta()).toMatchObject({ page: 1, page_size: 25 });
  });

  it('a reload that leaves no tacticals at all goes back to the first page', async () => {
    const muchos = Array.from({ length: 25 }, (_, i) => ({ ...REBATE, id: 100 + i, nombre: `Rebate ${i + 1}` }));
    tacticalsAPI.listar.mockImplementation(async ({ page }) => ({
      data: page === 1 ? pagina(muchos, 26) : pagina([{ ...REBATE, id: 200, nombre: 'Rebate 26' }], 26, 2),
    }));
    const { rerender } = render(<TacticalsList marcas={MARCAS} />);
    await screen.findByText('Rebate 1');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /filas/i }), '25');
    await userEvent.click(screen.getByRole('button', { name: /siguiente/i }));
    expect(await screen.findByText('Rebate 26')).toBeInTheDocument();

    tacticalsAPI.listar.mockResolvedValue({ data: pagina([], 0) });
    rerender(<TacticalsList marcas={MARCAS} version={1} />);

    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ page: 1, page_size: 25 }));
    expect(await screen.findByText('mostrando 0-0 de 0')).toBeInTheDocument();
    expect(screen.getByText('No hay tacticals con estos filtros.')).toBeInTheDocument();
  });
});

describe('TacticalsList same query on a later page', () => {
  it('a trailing space in Buscar on page 2 keeps that page and its open rows', async () => {
    const muchos = Array.from({ length: 25 }, (_, i) => ({ ...REBATE, id: 100 + i, nombre: `Rebate ${i + 1}` }));
    tacticalsAPI.listar.mockImplementation(async ({ page }) => ({
      data: page === 1 ? pagina(muchos, 26) : pagina([{ ...REBATE, id: 200, nombre: 'Rebate 26' }], 26, 2),
    }));
    render(<TacticalsList marcas={MARCAS} />);
    await screen.findByText('Rebate 1');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /filas/i }), '25');
    await userEvent.click(screen.getByRole('button', { name: /siguiente/i }));
    await userEvent.click(await screen.findByRole('button', { name: 'Ver las líneas de Rebate 26' }));
    const pedidos = tacticalsAPI.listar.mock.calls.length;

    await userEvent.type(screen.getByRole('searchbox', { name: 'Buscar por nombre o referencia' }), ' ');
    await new Promise((resolve) => setTimeout(resolve, 400));

    expect(screen.getByRole('button', { name: 'Ocultar las líneas de Rebate 26' })).toBeInTheDocument();
    expect(tacticalsAPI.listar).toHaveBeenCalledTimes(pedidos);
  });

  it('changing the rows per page closes the open rows', async () => {
    render(<TacticalsList marcas={MARCAS} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' }));

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /filas/i }), '25');

    expect(await screen.findByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' })).toBeInTheDocument();
  });
});

describe('TacticalsList empty and error', () => {
  it('says there are none under the filters', async () => {
    tacticalsAPI.listar.mockResolvedValue({ data: pagina([], 0) });
    render(<TacticalsList marcas={MARCAS} />);
    expect(await screen.findByText('No hay tacticals con estos filtros.')).toBeInTheDocument();
  });

  it('says the list could not be loaded', async () => {
    tacticalsAPI.listar.mockRejectedValue(new Error('500'));
    render(<TacticalsList marcas={MARCAS} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los tacticals.');
  });
});

describe('TacticalsList row actions', () => {
  it('offers Renovar on the tacticals whose kind the user manages, and hands the tactical over', async () => {
    const onRenovar = vi.fn();
    render(<TacticalsList marcas={MARCAS} puedeGestionar={(tipo) => tipo === 'sell_out'} onRenovar={onRenovar} />);
    await screen.findByText('Tacticals BPS Noviembre Q1FY27');

    expect(within(filaDe('Rebate HP Q1FY27')).queryByRole('button', { name: /Acciones/ })).not.toBeInTheDocument();
    const acciones = within(filaDe('Tacticals BPS Noviembre Q1FY27')).getByRole('button', {
      name: 'Acciones de Tacticals BPS Noviembre Q1FY27',
    });
    expect(acciones).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(acciones);
    expect(acciones).toHaveAttribute('aria-expanded', 'true');
    await userEvent.click(screen.getByRole('menuitem', { name: 'Renovar' }));

    expect(onRenovar).toHaveBeenCalledWith(BPS);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes the menu with Escape, back on its button', async () => {
    render(<TacticalsList marcas={MARCAS} puedeGestionar={() => true} onRenovar={vi.fn()} />);
    const acciones = await screen.findByRole('button', { name: 'Acciones de Rebate HP Q1FY27' });

    await userEvent.click(acciones);
    expect(screen.getByRole('menuitem', { name: 'Editar' })).toHaveFocus();
    await userEvent.keyboard('{Escape}');

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(acciones).toHaveFocus();
  });

  it('offers Editar on a live tactical only, before Renovar', async () => {
    const ANULADO = { ...REBATE, id: 4, nombre: 'Rebate anulado', estado: 'anulado' };
    tacticalsAPI.listar.mockResolvedValue({ data: pagina([BPS, ANULADO], 2) });
    render(<TacticalsList marcas={MARCAS} puedeGestionar={() => true} onRenovar={vi.fn()} />);

    await userEvent.click(await screen.findByRole('button', { name: 'Acciones de Tacticals BPS Noviembre Q1FY27' }));
    expect(screen.getAllByRole('menuitem').map((i) => i.textContent)).toEqual(['Editar', 'Renovar', 'Anular']);
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('button', { name: 'Acciones de Rebate anulado' }));
    expect(screen.getAllByRole('menuitem').map((i) => i.textContent)).toEqual(['Renovar']);
  });
});

describe('TacticalsList Editar', () => {
  const abrirEditar = async () => {
    render(<TacticalsList marcas={MARCAS} puedeGestionar={() => true} onRenovar={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Acciones de Tacticals BPS Noviembre Q1FY27' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Editar' }));
    return screen.getByRole('dialog', { name: 'Editar Tacticals BPS Noviembre Q1FY27' });
  };

  it('saves only what changed, closes and asks the list again', async () => {
    tacticalsAPI.editar.mockResolvedValue({ data: BPS });
    const dialogo = await abrirEditar();

    expect(within(dialogo).getByLabelText('Nombre')).toHaveValue('Tacticals BPS Noviembre Q1FY27');
    expect(within(dialogo).getByText('Ya usó 62 u · USD 12.760')).toBeInTheDocument();
    const fecha = within(dialogo).getByLabelText('Fecha hasta');
    await userEvent.clear(fecha);
    await userEvent.type(fecha, '2026-12-31');
    const tope = within(dialogo).getByLabelText('Tope de unidades de la línea 1');
    await userEvent.clear(tope);
    await userEvent.type(tope, '120');
    const pedidas = tacticalsAPI.listar.mock.calls.length;
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Guardar cambios' }));

    expect(tacticalsAPI.editar).toHaveBeenCalledWith(1, { fecha_hasta: '2026-12-31', lineas: [{ linea: 1, tope_unidades: 120 }] });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(tacticalsAPI.listar.mock.calls.length).toBeGreaterThan(pedidas);
  });

  it("shows the server's refusal inside the dialog and keeps it open", async () => {
    tacticalsAPI.editar.mockRejectedValue({
      response: { status: 422, data: { error: { message: 'Línea 1: el tope de unidades (10) no puede quedar debajo de lo ya usado (62)' } } },
    });
    const dialogo = await abrirEditar();
    const tope = within(dialogo).getByLabelText('Tope de unidades de la línea 1');
    await userEvent.clear(tope);
    await userEvent.type(tope, '10');
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Guardar cambios' }));

    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('no puede quedar debajo de lo ya usado (62)');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('does not send a form it cannot read, and Escape closes without saving', async () => {
    const dialogo = await abrirEditar();
    await userEvent.clear(within(dialogo).getByLabelText('Nombre'));
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Guardar cambios' }));

    expect(within(dialogo).getByRole('alert')).toHaveTextContent('El nombre no puede quedar vacío.');
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(tacticalsAPI.editar).not.toHaveBeenCalled();
  });
});

describe('TacticalsList Anular', () => {
  const abrirAnular = async (nombre) => {
    render(<TacticalsList marcas={MARCAS} puedeGestionar={() => true} onRenovar={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: `Acciones de ${nombre}` }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Anular' }));
    return screen.getByRole('dialog', { name: `¿Anular ${nombre}?` });
  };

  it('says what voiding a sell out tactical reverses, sends the reason and asks the list again', async () => {
    tacticalsAPI.anular.mockResolvedValue({ data: { ...BPS, estado: 'anulado' } });
    const dialogo = await abrirAnular('Tacticals BPS Noviembre Q1FY27');

    expect(dialogo).toHaveTextContent('Sus campañas dejan de acreditar y se recalculan las ventas que alcanzaban.');
    expect(dialogo).toHaveTextContent('Esta acción no se puede deshacer.');
    await userEvent.type(within(dialogo).getByLabelText('Motivo (opcional)'), 'Cargado por error');
    const pedidas = tacticalsAPI.listar.mock.calls.length;
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Anular tactical' }));

    expect(tacticalsAPI.anular).toHaveBeenCalledWith(1, 'Cargado por error');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(tacticalsAPI.listar.mock.calls.length).toBeGreaterThan(pedidas);
  });

  it("says what voiding a sell in tactical reverses; without a reason it sends none", async () => {
    tacticalsAPI.anular.mockResolvedValue({ data: { ...REBATE, estado: 'anulado' } });
    const dialogo = await abrirAnular('Rebate HP Q1FY27');

    expect(dialogo).toHaveTextContent(
      'Sus bonos dejan de aplicarse y se anulan las compras que generaron: las ventas que tomaban pasan a las compras siguientes.',
    );
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Anular tactical' }));
    expect(tacticalsAPI.anular).toHaveBeenCalledWith(3, null);
  });

  it("shows the server's refusal inside the dialog; Cancelar voids nothing", async () => {
    tacticalsAPI.anular.mockRejectedValue({ response: { status: 409, data: { error: { message: 'El tactical ya está anulado' } } } });
    const dialogo = await abrirAnular('Rebate HP Q1FY27');
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Anular tactical' }));

    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('El tactical ya está anulado');
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('while voiding, Cancelar and Escape wait for the answer', async () => {
    let responder;
    tacticalsAPI.anular.mockReturnValue(new Promise((resolve) => (responder = resolve)));
    const dialogo = await abrirAnular('Rebate HP Q1FY27');
    await userEvent.click(within(dialogo).getByRole('button', { name: 'Anular tactical' }));

    expect(within(dialogo).getByRole('button', { name: 'Cancelar' })).toBeDisabled();
    await userEvent.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    responder({ data: {} });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});

describe('TacticalsList Ver ventas', () => {
  it("hands each line's record to onVerLinea, and shows no button without it", async () => {
    const onVerLinea = vi.fn();
    const { unmount } = render(<TacticalsList marcas={MARCAS} onVerLinea={onVerLinea} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' }));
    await userEvent.click(screen.getByRole('button', { name: 'Ver ventas de la línea 3' }));

    expect(onVerLinea).toHaveBeenCalledWith(BPS.lineas[2]);
    unmount();
    render(<TacticalsList marcas={MARCAS} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' }));
    expect(screen.queryByRole('button', { name: /Ver ventas/ })).not.toBeInTheDocument();
  });
});
