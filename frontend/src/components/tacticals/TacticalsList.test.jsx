/**
 * Tactical list by brand (owner, 2026-11-04, S7: "el tactical tiene que podersele cargar una marca adjunta para
 * después poder filtrar por marca"). Built from the pending design handoffs/diseno-tactical/listado-tacticals-PENDIENTE.html
 * on the draft contract of GET /api/tacticals (handoffs/tactical-tarea.md). The fixtures carry the design's numbers;
 * swap them for a real capture once T1's endpoint exists.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TacticalsList from './TacticalsList';
import { tacticalsAPI } from '../../services/tacticalsAPI';

vi.mock('../../services/tacticalsAPI', () => ({ tacticalsAPI: { listar: vi.fn() } }));

const BPS = {
  id: 1,
  tipo: 'sell_out',
  nombre: 'Tacticals BPS Noviembre Q1FY27',
  marca: 'HP',
  referencia: 'Q1 FY27 · BPS',
  fecha_desde: '2026-11-01',
  fecha_hasta: '2026-11-30',
  moneda: 'USD',
  estado: 'activo',
  lineas: [
    {
      id: 11,
      alcance: 'productos',
      productos: [{ item_id: 101, descripcion: 'AIO HP G2 R5 16G 512 W11H' }],
      modo_monto: 'por_unidad',
      valor: '220',
      tope_unidades: 90,
      tope_monto: null,
      unidades_usadas: 58,
      monto_usado: '12760',
    },
    {
      id: 12,
      alcance: 'productos',
      productos: [{ item_id: 102, descripcion: 'Notebook HP 250RG10 5-120U' }],
      modo_monto: 'por_unidad',
      valor: '100',
      tope_unidades: 62,
      tope_monto: null,
      unidades_usadas: 62,
      monto_usado: '6200',
    },
    {
      id: 13,
      alcance: 'productos',
      productos: [
        { item_id: 201, descripcion: 'Monitor V24i G5' },
        { item_id: 202, descripcion: 'Monitor V27i G5' },
      ],
      modo_monto: 'por_unidad',
      valor: '12',
      tope_unidades: 300,
      tope_monto: '3000',
      unidades_usadas: 132,
      monto_usado: '1584',
    },
  ],
};

const REBATE = {
  id: 3,
  tipo: 'sell_in',
  nombre: 'Rebate HP Q1FY27',
  marca: 'HP',
  referencia: null,
  fecha_desde: '2026-11-01',
  fecha_hasta: '2027-01-31',
  moneda: 'ARS',
  estado: 'activo',
  lineas: [
    {
      id: 31,
      alcance: 'marca',
      marca: 'HP',
      modo_monto: 'porcentaje',
      valor: '3.5',
      tope_unidades: null,
      tope_monto: null,
      unidades_usadas: null,
      monto_usado: '1240000',
    },
  ],
};

const MARCAS = ['HP', 'Lenovo', 'TP-Link'];

const filaDe = (nombre) => screen.getByRole('row', { name: new RegExp(nombre) });
const ultimaConsulta = () => tacticalsAPI.listar.mock.calls.at(-1)[0];

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 10, 12, 10));
  tacticalsAPI.listar.mockResolvedValue({ data: { items: [BPS, REBATE], total: 2 } });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('TacticalsList rows', () => {
  it('asks the current tacticals and shows each with its type, brand, dates, lines, progress and state', async () => {
    render(<TacticalsList marcas={MARCAS} />);

    expect(await screen.findByText('Tacticals BPS Noviembre Q1FY27')).toBeInTheDocument();
    expect(tacticalsAPI.listar).toHaveBeenCalledWith({ estado: 'vigentes', page: 1, page_size: 50 });

    const bps = within(filaDe('Tacticals BPS Noviembre Q1FY27'));
    expect(bps.getByText('Q1 FY27 · BPS')).toBeInTheDocument();
    expect(bps.getByText('Sell out')).toBeInTheDocument();
    expect(bps.getByText('HP')).toBeInTheDocument();
    expect(bps.getByText('01/11 al 30/11/2026')).toBeInTheDocument();
    expect(bps.getByText('3')).toBeInTheDocument();
    expect(bps.getByText('252 / 452 u')).toBeInTheDocument();
    expect(bps.getByText('USD 20.544')).toBeInTheDocument();
    expect(bps.getByRole('img', { name: '55,8% de las unidades consumidas' })).toBeInTheDocument();
    expect(bps.getByText('Vigente')).toBeInTheDocument();

    const rebate = within(filaDe('Rebate HP Q1FY27'));
    expect(rebate.getByText('Sell in')).toBeInTheDocument();
    expect(rebate.getByText('01/11 al 31/01/2027')).toBeInTheDocument();
    expect(rebate.getByText('ARS 1.240.000')).toBeInTheDocument();
    expect(rebate.queryByRole('img')).not.toBeInTheDocument();
  });

  it('expanding a tactical lists its lines with amount, caps, usage and a reached cap', async () => {
    render(<TacticalsList marcas={MARCAS} />);
    await screen.findByText('Tacticals BPS Noviembre Q1FY27');
    expect(screen.queryByText('AIO HP G2 R5 16G 512 W11H')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' }));

    expect(screen.getByText('Líneas del tactical (3)')).toBeInTheDocument();
    const celdas = (texto) => within(screen.getByText(texto).closest('tr')).getAllByRole('cell').map((c) => c.textContent);
    // Qué incluye, Monto, Tope unidades, Usadas, Tope monto, Usado, Avance
    expect(celdas('AIO HP G2 R5 16G 512 W11H')).toEqual(['AIO HP G2 R5 16G 512 W11H', 'USD 220 / u', '90', '58', '—', 'USD 12.760', '']);
    expect(celdas('Notebook HP 250RG10 5-120U')).toEqual([
      'Notebook HP 250RG10 5-120U',
      'USD 100 / u',
      '62',
      '62',
      '—',
      'USD 6.200',
      'Tope alcanzado',
    ]);
    expect(celdas('Monitor V24i G5')[0]).toBe('Monitor V24i G5Monitor V27i G5');
    expect(celdas('Monitor V24i G5').slice(1, 6)).toEqual(['USD 12 / u', '300', '132', 'USD 3.000', 'USD 1.584']);
    expect(screen.getByRole('button', { name: 'Ocultar las líneas de Tacticals BPS Noviembre Q1FY27' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('a brand line says it reaches every product of the brand', async () => {
    render(<TacticalsList marcas={MARCAS} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Ver las líneas de Rebate HP Q1FY27' }));

    const fila = screen.getByText('Marca HP').closest('tr');
    expect(within(fila).getByText('Todos los productos de la marca')).toBeInTheDocument();
    expect(within(fila).getByText('3,5 %')).toBeInTheDocument();
  });
});

describe('TacticalsList filters', () => {
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
    await userEvent.type(screen.getByRole('searchbox', { name: 'Buscar por nombre o producto' }), 'bps');
    await waitFor(() => expect(ultimaConsulta()).toMatchObject({ q: 'bps' }));

    await userEvent.click(screen.getByRole('button', { name: 'Limpiar filtros' }));
    await waitFor(() => expect(ultimaConsulta()).toEqual({ estado: 'vigentes', page: 1, page_size: 50 }));
    expect(screen.getByLabelText('Marca')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Vigentes' })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('TacticalsList empty and error', () => {
  it('says there are none under the filters', async () => {
    tacticalsAPI.listar.mockResolvedValue({ data: { items: [], total: 0 } });
    render(<TacticalsList marcas={MARCAS} />);
    expect(await screen.findByText('No hay tacticals con estos filtros.')).toBeInTheDocument();
  });

  it('says the list could not be loaded', async () => {
    tacticalsAPI.listar.mockRejectedValue(new Error('500'));
    render(<TacticalsList marcas={MARCAS} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los tacticals.');
  });
});
