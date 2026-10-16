import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { TP_COLUMNS } from './ventasMlTpColumns';
import { COLUMNS } from './ventasMlColumns';

const totalTp = TP_COLUMNS.find((c) => c.id === 'total_tp');

function renderCell(ctx) {
  render(<div data-testid="cell">{totalTp.cell(ctx)}</div>);
  return screen.getByTestId('cell');
}

const order = (over = {}) => ({
  order_id: 1,
  currency_id: 'ARS',
  metrics_state: 'ok',
  total_tp: 811.02,
  markup_tp: 21.6,
  tp_incompleto: false,
  ...over,
});

describe('TP columns', () => {
  it('replace Total Gauss with Total TP and keep every other column in place', () => {
    expect(TP_COLUMNS.map((c) => c.id)).toEqual(COLUMNS.map((c) => (c.id === 'total_gauss' ? 'total_tp' : c.id)));
    expect(TP_COLUMNS.some((c) => /gauss/i.test(`${c.id} ${c.header}`))).toBe(false);
    expect(totalTp.header).toBe('Total TP');
    expect(totalTp.enableHiding).toBe(false);
  });

  it('shows the Total TP and the lone sale TP markup', () => {
    const o = order();
    const cell = renderCell({ kind: 'group', group: { ...o }, orders: [o], loneOrder: o, metricsState: 'ok' });
    expect(cell).toHaveTextContent('811,02');
    expect(cell).toHaveTextContent('21,6%');
  });

  it('shows a dash with "incompleto", never 0, when the TP figure is unknown', () => {
    const o = order({ total_tp: null, markup_tp: null, tp_incompleto: true });
    const cell = renderCell({ kind: 'member', order: o });
    expect(cell).toHaveTextContent('—');
    expect(cell).toHaveTextContent('incompleto');
    expect(cell).not.toHaveTextContent(/\b0,00\b/);
  });

  it('flags an incomplete pack row too', () => {
    const group = { currency_id: 'ARS', total_tp: null, tp_incompleto: true };
    const cell = renderCell({ kind: 'group', group, orders: [order(), order()], loneOrder: null, metricsState: 'ok' });
    expect(cell).toHaveTextContent('incompleto');
  });

  it('keeps the recalculating badge while the metrics are not settled', () => {
    const o = order({ metrics_state: 'pending', total_tp: null, tp_incompleto: true });
    const cell = renderCell({ kind: 'member', order: o });
    expect(within(cell).getByRole('status')).toHaveAttribute('data-state', 'pending');
    expect(cell).not.toHaveTextContent('incompleto');
  });
});
