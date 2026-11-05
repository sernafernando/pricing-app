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

vi.mock('../../services/tacticalsAPI', () => ({ tacticalsAPI: { listar: vi.fn() } }));

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
    await userEvent.click(screen.getByRole('button', { name: 'Anulados' }));
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ estado: 'anulados' }));
    await userEvent.type(screen.getByLabelText('Desde'), '2026-11-01');
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ desde: '2026-11-01' }));
    await userEvent.type(screen.getByRole('searchbox', { name: 'Buscar por nombre o referencia' }), 'bps');
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ q: 'bps' }));

    await userEvent.click(screen.getByRole('button', { name: 'Limpiar filtros' }));
    await waitFor(() => expect(ultimaConsulta()).toEqual({ estado: 'vigentes', page: 1, page_size: 50 }));
    expect(screen.getByLabelText('Marca')).toHaveValue('');
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
    expect(screen.getByRole('menuitem', { name: 'Renovar' })).toHaveFocus();
    await userEvent.keyboard('{Escape}');

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(acciones).toHaveFocus();
  });
});
