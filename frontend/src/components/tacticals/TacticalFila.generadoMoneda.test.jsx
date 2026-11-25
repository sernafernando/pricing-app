/**
 * Sell in incident 2026-11-24, S1: a % cost line's usage is read in the currency of the costo SI steps it got (the
 * products' cost currency), one amount per currency (`montos_usados`), never converted to the line's stored currency.
 * "TP loyalty 18.18M ARS must read USD 11,648".
 */
import { useState } from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TacticalFila from './TacticalFila';
import { TACTICAL_REBATE } from './tacticalsFixtures';

const LINEA_LOYALTY = {
  ...TACTICAL_REBATE.lineas[0],
  id: 98,
  marca: 'TP-LINK',
  valor: '3.6',
  tope_monto: null,
};

/** Tactical 62 as GET /api/tacticals answers it once the steps' currency is kept (bono 98, 173 steps, 11,954 u). */
const LOYALTY = {
  ...TACTICAL_REBATE,
  id: 62,
  nombre: 'TPLINK LOYALTY',
  marca: 'TP-LINK',
  moneda: 'USD',
  tc_modo: 'dia_venta',
  fecha_desde: '2026-10-01',
  fecha_hasta: '2026-12-31',
  lineas: [
    {
      ...LINEA_LOYALTY,
      moneda: 'USD',
      unidades_usadas: 11954,
      monto_usado: '11648.08',
      montos_usados: [{ moneda: 'USD', monto: '11648.08' }],
    },
  ],
};

/** The same % line over a USD and an ARS product: one amount per currency, none converted. */
const MIXTO = {
  ...LOYALTY,
  id: 64,
  nombre: 'TPLINK MIXTO',
  lineas: [
    {
      ...LINEA_LOYALTY,
      moneda: 'ARS',
      unidades_usadas: 130,
      monto_usado: '9668.48',
      montos_usados: [
        { moneda: 'ARS', monto: '9668.48' },
        { moneda: 'USD', monto: '38.43' },
      ],
    },
  ],
};

function Fila({ tactical }) {
  const [abierto, setAbierto] = useState(false);
  return (
    <table>
      <TacticalFila tactical={tactical} abierto={abierto} onAlternar={() => setAbierto((a) => !a)} />
    </table>
  );
}

const celdas = (texto) => within(screen.getByText(texto).closest('tr')).getAllByRole('cell').map((c) => c.textContent);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 10, 24, 10));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('TacticalFila — a % cost line in its steps currency', () => {
  it('shows TP loyalty as USD 11.648,08 on the row and on its line', async () => {
    render(<Fila tactical={LOYALTY} />);

    const fila = within(screen.getByRole('row', { name: /TPLINK LOYALTY/ }));
    expect(fila.getByText('USD 11.648,08')).toBeInTheDocument();
    expect(fila.queryByText(/ARS/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Ver las líneas de TPLINK LOYALTY' }));
    // Qué incluye, Monto, Tope unidades, Usadas, Tope monto, Usado, Avance
    expect(celdas('Marca TP-LINK').slice(1, 6)).toEqual(['3,6 %', '—', '11.954', '—', 'USD 11.648,08']);
  });

  it('shows one amount per currency when the line got USD and ARS products', async () => {
    render(<Fila tactical={MIXTO} />);

    const fila = within(screen.getByRole('row', { name: /TPLINK MIXTO/ }));
    expect(fila.getByText('ARS 9.668,48 · USD 38,43')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Ver las líneas de TPLINK MIXTO' }));
    expect(celdas('Marca TP-LINK')[5]).toBe('ARS 9.668,48 · USD 38,43');
  });
});
