/**
 * One row of the tactical list (pending design handoffs/diseno-tactical/listado-tacticals-PENDIENTE.html) on the final
 * contract of GET /api/tacticals (handoffs/tactical-tarea.md, "Contrato final"): the tactical's row and its lines.
 */
import { useState } from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TacticalFila from './TacticalFila';
import { TACTICAL_BPS, TACTICAL_REBATE, lineaDeProducto } from './tacticalsFixtures';

const BPS = TACTICAL_BPS;
const REBATE = TACTICAL_REBATE;

/** The rows inside a table, each opening and closing on its toggle like the list does. */
function Filas({ tacticals }) {
  const [abiertos, setAbiertos] = useState([]);
  const alternar = (id) => setAbiertos((a) => (a.includes(id) ? a.filter((x) => x !== id) : [...a, id]));
  return (
    <table>
      {tacticals.map((t) => (
        <TacticalFila key={t.id} tactical={t} abierto={abiertos.includes(t.id)} onAlternar={() => alternar(t.id)} />
      ))}
    </table>
  );
}

const renderFilas = (tacticals) => render(<Filas tacticals={tacticals} />);
const filaDe = (nombre) => screen.getByRole('row', { name: new RegExp(nombre) });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 10, 12, 10));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('TacticalFila row', () => {
  it('shows each tactical with its type, brand, dates, lines, progress and state', () => {
    renderFilas([BPS, REBATE]);

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
    renderFilas([BPS]);
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
    renderFilas([REBATE]);
    await userEvent.click(screen.getByRole('button', { name: 'Ver las líneas de Rebate HP Q1FY27' }));

    const fila = screen.getByText('Marca HP').closest('tr');
    expect(within(fila).getByText('Todos los productos de la marca')).toBeInTheDocument();
    expect(within(fila).getByText('3,5 %')).toBeInTheDocument();
  });
});

describe('TacticalFila money cap', () => {
  it('when every line has a money cap the row says how much of it was used, both in the currency', async () => {
    const conTopes = {
      ...BPS,
      lineas: BPS.lineas.map((linea, i) => ({ ...linea, tope_monto: ['15000', '6200', '3000'][i] })),
    };
    renderFilas([conTopes]);

    expect(screen.getByText('USD 20.544 de USD 24.200')).toBeInTheDocument();
  });
});

describe('TacticalFila brands (S3)', () => {
  it('shows every brand of a tactical with several, and the one brand of an older read', () => {
    renderFilas([{ ...REBATE, marcas: ['HP', 'TP-Link'] }]);

    expect(within(filaDe('Rebate HP Q1FY27')).getAllByRole('cell')[3]).toHaveTextContent('HP, TP-Link');
  });
});

describe('TacticalFila missing values', () => {
  it('shows a dash for a missing brand and an empty cap, and measures the money cap then', async () => {
    const sinDatos = {
      ...REBATE,
      marca: null,
      lineas: [{ ...REBATE.lineas[0], tope_unidades: '', tope_monto: '2000', monto_usado: '500' }],
    };
    renderFilas([sinDatos]);

    expect(within(filaDe('Rebate HP Q1FY27')).getAllByRole('cell')[3]).toHaveTextContent('—');
    await userEvent.click(screen.getByRole('button', { name: 'Ver las líneas de Rebate HP Q1FY27' }));
    const linea = screen.getByText('Marca HP').closest('tr');
    expect(within(linea).getAllByRole('cell')[2]).toHaveTextContent('—');
    expect(within(linea).getByRole('img', { name: '25% del tope de monto' })).toBeInTheDocument();
  });
});

describe('TacticalFila line order', () => {
  it('lists the lines in the order they were loaded: by linea, then by child', async () => {
    const desordenado = {
      ...BPS,
      lineas: [
        lineaDeProducto(30, 301, 'C', 'Producto C', 10, 5, 1, 2),
        lineaDeProducto(21, 302, 'B', 'Producto B', 10, 5, 1, 1),
        lineaDeProducto(20, 303, 'A', 'Producto A', 10, 5, 1, 1),
      ],
    };
    renderFilas([desordenado]);
    await userEvent.click(screen.getByRole('button', { name: `Ver las líneas de ${BPS.nombre}` }));

    const productos = screen.getAllByText(/^Producto [ABC]$/).map((chip) => chip.textContent);
    expect(productos).toEqual(['Producto A', 'Producto B', 'Producto C']);
  });
});

describe('TacticalFila invoice total waiting for its invoice', () => {
  it('a waiting invoice total has no sales to show, the other lines keep Ver ventas', async () => {
    const pendiente = {
      ...REBATE,
      lineas: [
        { ...REBATE.lineas[0], linea: 1 },
        {
          ...REBATE.lineas[0],
          id: 9,
          linea: 2,
          origen: 'sell_in_factura_pendiente',
          alcance: 'factura',
          pedido_numero: '12345',
          modo_monto: 'monto_total',
          esperando_factura: true,
        },
      ],
    };
    const onVerLinea = vi.fn();
    render(
      <table>
        <TacticalFila tactical={pendiente} abierto onAlternar={() => {}} onVerLinea={onVerLinea} />
      </table>,
    );

    expect(screen.getByRole('button', { name: 'Ver ventas de la línea 1' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ver ventas de la línea 2' })).not.toBeInTheDocument();
  });
});
