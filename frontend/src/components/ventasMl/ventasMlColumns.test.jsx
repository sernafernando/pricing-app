import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { COLUMNS } from './ventasMlColumns';

const importe = COLUMNS.find((c) => c.id === 'importe');

function renderCell(ctx) {
  const view = render(<div data-testid="cell">{importe.cell(ctx)}</div>);
  const cell = screen.getByTestId('cell');
  return Object.assign(cell, { unmount: view.unmount });
}

const order = (over = {}) => ({ order_id: 1, total_amount: 1000, currency_id: 'ARS', ...over });

describe('Importe cell: ML coupon sub-line', () => {
  it('shows "cupón ML $X" under the amount when the order carries a coupon', () => {
    const o = order({ coupon_amount: 150 });
    const cell = renderCell({ kind: 'group', group: { total_amount: 1000, currency_id: 'ARS' }, orders: [o] });
    expect(cell).toHaveTextContent('1.000,00');
    expect(cell).toHaveTextContent('cupón ML $ 150,00');
  });

  it('sums the coupons of every order in a pack', () => {
    const orders = [order({ order_id: 1, coupon_amount: 100 }), order({ order_id: 2, coupon_amount: 50.5 })];
    const cell = renderCell({ kind: 'group', group: { total_amount: 2000, currency_id: 'ARS' }, orders });
    expect(cell).toHaveTextContent('cupón ML $ 150,50');
  });

  it('shows no sub-line when the coupon is zero, null or absent', () => {
    for (const coupon_amount of [0, null, undefined]) {
      const cell = renderCell({
        kind: 'group',
        group: { total_amount: 1000, currency_id: 'ARS' },
        orders: [order({ coupon_amount })],
      });
      expect(cell).not.toHaveTextContent('cupón');
      cell.unmount();
    }
  });

  it('a pack-member row shows its own coupon', () => {
    const cell = renderCell({ kind: 'member', order: order({ coupon_amount: 75 }) });
    expect(cell).toHaveTextContent('cupón ML $ 75,00');
  });
});

describe('Sell in / out cell (Métricas audit A7)', () => {
  const sell = COLUMNS.find((c) => c.id === 'sell_in_out');
  const renderSell = (ctx) => {
    const view = render(<div data-testid="sell">{sell.cell(ctx)}</div>);
    return Object.assign(screen.getByTestId('sell'), { unmount: view.unmount, tooltip: sell.cellProps(ctx).title });
  };

  it('shows the sell in with the sell out on the sub-line, and names both in the tooltip', () => {
    const cell = renderSell({ kind: 'member', order: order({ sell_in_ars: 1200.5, sell_out_ars: 300, sell_out_estimado: false }) });
    expect(cell).toHaveTextContent('1.200,50');
    expect(cell).toHaveTextContent('out $ 300,00');
    expect(cell.tooltip).toBe('Sell in: $ 1.200,50 · Sell out: $ 300,00');
  });

  it('a pack row reads the pack sums', () => {
    const cell = renderSell({ kind: 'group', group: { sell_in_ars: 10, sell_out_ars: null, sell_out_estimado: null }, orders: [] });
    expect(cell).toHaveTextContent('10,00');
    expect(cell).not.toHaveTextContent('out');
  });

  it('an estimated sell out is marked, an unknown one says it is not defined yet', () => {
    let cell = renderSell({ kind: 'member', order: order({ sell_out_ars: 50, sell_out_estimado: true }) });
    expect(cell).toHaveTextContent('out ≈ $ 50,00');
    cell.unmount();
    cell = renderSell({ kind: 'member', order: order({ sell_out_ars: null, sell_out_estimado: true }) });
    expect(cell).toHaveTextContent('out a definir');
    expect(cell.tooltip).toBe('Sell out en USD sin tipo de cambio');
  });

  it('a sale with nothing applied shows a dash and no tooltip', () => {
    const cell = renderSell({ kind: 'member', order: order() });
    expect(cell).toHaveTextContent('—');
    expect(cell).not.toHaveTextContent('out');
    expect(cell.tooltip).toBeUndefined();
  });

  it('can be hidden', () => {
    expect(sell.enableHiding).not.toBe(false);
  });
});
