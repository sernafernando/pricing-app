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
